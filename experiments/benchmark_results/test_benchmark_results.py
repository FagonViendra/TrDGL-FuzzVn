from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import collect_benchmark_results as collector
import collect_benchmark_campaign as campaign_collector
import audit_checkpoint_provenance as checkpoint_audit

try:
    import jsonschema
except ImportError:
    jsonschema = None


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NOTEBOOK = HERE.parent / "benchmark_120/trdgl_fair_benchmark_120.ipynb"
SMOKE = ROOT / "tmp/colab_smoke_4baseline/events_latest.jsonl"
REAL_CHECKPOINT_INDEX = HERE / "campaign_checkpoint/campaign_shards.json"
SIG = "7" * 64


def event(task: dict, baseline: str, signature: str = SIG) -> dict:
    prompt = "8" * 64 if baseline in {"B2", "B3"} else ("9" * 64 if baseline == "B1" else "a" * 64)
    return {
        "run_signature": signature, "started_utc": "2026-07-08T00:00:00+00:00",
        "finished_utc": "2026-07-08T00:00:01+00:00", "baseline": baseline,
        "model": baseline, "task_id": task["task_id"], "api": task["api"],
        "api_group": task["api_group"], "api_index": task["api_index"],
        "generation_seed": task["generation_seed"], "ab_order": task["ab_order"],
        "logical_baseline_order": task["logical_baseline_order"], "prompt_sha256": prompt,
        "raw_output_sha256": "b" * 64, "raw_generation": True,
        "generation_seconds": 0.1, "seed_backend": "host+torch template" if baseline == "B0" else "host+torch+cuda+llama_cpp.set_seed+completion(seed)",
        "parseable": True, "ast_pass": True, "target_call_present": True,
        "oracle_present": True, "fake_assertion": False, "subprocess_seconds": 0.2,
        "runnable": True, "target_valid": True, "oracle_bearing": True,
    }


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class BenchmarkResultTests(unittest.TestCase):
    def test_checkpoint_audit_does_not_treat_stdout_as_raw_evidence(self) -> None:
        source = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        index = json.loads(REAL_CHECKPOINT_INDEX.read_text(encoding="utf-8"))
        shard = index["shards"][0]
        events = (REAL_CHECKPOINT_INDEX.parent / shard["events_path"]).resolve()
        run_manifest = (REAL_CHECKPOINT_INDEX.parent / shard["run_manifest_path"]).resolve()
        checkpoint_manifest = json.loads((events.parent / "checkpoint_manifest.json").read_text(encoding="utf-8"))
        transcript_observed = (
            checkpoint_manifest["observed_events"] + 1
            if checkpoint_manifest["observed_events"] < checkpoint_manifest["expected_events"]
            else checkpoint_manifest["observed_events"] - 1
        )
        source["cells"][-1]["outputs"] = [{
            "output_type": "stream", "name": "stdout",
            "text": [f"Runner finished. Events for this signature: {transcript_observed} / {checkpoint_manifest['expected_events']}\n"],
        }]
        with tempfile.TemporaryDirectory() as directory:
            executed = Path(directory) / "executed.ipynb"
            executed.write_text(json.dumps(source), encoding="utf-8")
            report = checkpoint_audit.audit(
                events,
                run_manifest,
                NOTEBOOK,
                executed,
                shard["run_signature"],
            )
        self.assertEqual(report["persisted_raw_event_count"], checkpoint_manifest["observed_events"])
        self.assertEqual(report["persisted_baseline_counts"], checkpoint_manifest["baseline_counts"])
        self.assertEqual(report["executed_notebook_transcript"]["observed_events"], transcript_observed)
        self.assertEqual(report["paper_evidence_event_count"], checkpoint_manifest["observed_events"])
        self.assertFalse(report["ready_for_campaign_index"])
        self.assertIn("executed_notebook_transcript_differs_from_persisted_raw_stream", report["blockers"])

    def test_campaign_index_rejects_reused_run_signature(self) -> None:
        shard = {
            "generation_seed": 3407, "run_signature": "1" * 64,
            "events_path": "a.jsonl", "run_manifest_path": "a.manifest.json",
            "executed_notebook_path": "a.ipynb",
        }
        index = {
            "schema_version": "trdgl_campaign_shard_index_v1",
            "evidence_label": "validation_only", "benchmark_id": "trdgl_pytorch_120_v1",
            "shards": [shard, {**shard, "generation_seed": 7711}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate run signature"):
                campaign_collector.load_index(path)

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.manifest_hash = collector.load_frozen_manifest(NOTEBOOK)
        cls.tasks = collector.expected_tasks(cls.manifest)
        cls.frozen_run = campaign_collector.frozen_run_contract(NOTEBOOK)

    def test_frozen_manifest_shape(self) -> None:
        self.assertEqual(self.manifest_hash, "d9de15ca10bdd4abef2106c58b661197f69d1f278f87eec2b6eb56845f4facac")
        self.assertEqual(len(self.tasks), 600)
        self.assertEqual(Counter(t["ab_order"] for t in self.tasks.values()), Counter({"B2_then_B3": 300, "B3_then_B2": 300}))

    def test_current_checkpoint_is_explicitly_incomplete(self) -> None:
        summary, cells = collector.summarize(SMOKE, NOTEBOOK, "validation_only")
        self.assertEqual(summary["coverage"]["observed_event_count"], 4)
        self.assertEqual(summary["coverage"]["missing_event_count"], 2396)
        self.assertFalse(summary["full_benchmark_complete"])
        self.assertFalse(summary["ready_for_paper_result"])
        self.assertEqual(len(cells), 200)
        coverage = collector.build_coverage_rows(NOTEBOOK, SMOKE)
        self.assertEqual(len(coverage), 2400)
        self.assertEqual(sum(row["observed"] for row in coverage), 4)
        self.assertEqual(sum(row["parseable"] is None for row in coverage), 2396)
        empty = next(c for c in cells if c["baseline"] == "B0" and c["api_group"] == "sparse" and c["generation_seed"] == 27103)
        self.assertEqual(empty["observed_events"], 0)
        self.assertIsNone(empty["parseable_rate"])

    def test_immutable_real_checkpoint_reconstructs_fail_closed(self) -> None:
        rows, campaign = campaign_collector.collect_shards(REAL_CHECKPOINT_INDEX, NOTEBOOK)
        shard = json.loads(REAL_CHECKPOINT_INDEX.read_text(encoding="utf-8"))["shards"][0]
        events = (REAL_CHECKPOINT_INDEX.parent / shard["events_path"]).resolve()
        checkpoint = json.loads((events.parent / "checkpoint_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), checkpoint["observed_events"])
        self.assertEqual(Counter(row["baseline"] for row in rows), Counter(checkpoint["baseline_counts"]))
        self.assertLess(checkpoint["observed_events"], 2400)
        self.assertEqual(campaign["declared_seeds"], [3407])
        self.assertFalse(campaign["all_seeds_present"])
        self.assertTrue(campaign["all_shards_complete"])
        self.assertEqual(
            campaign["shards"][0]["events_sha256"],
            checkpoint["artifacts"]["events.checkpoint.jsonl"]["sha256"],
        )

    def test_complete_synthetic_contract_passes_campaign_gate(self) -> None:
        rows = [event(task, baseline) for task in self.tasks.values() for baseline in collector.BASELINES]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, rows)
            summary, cells = collector.summarize(path, NOTEBOOK, "campaign")
        self.assertEqual(summary["coverage"]["observed_event_count"], 2400)
        self.assertTrue(summary["full_benchmark_complete"])
        self.assertTrue(summary["ready_for_paper_result"])
        self.assertEqual(summary["fairness"]["observed_complete_pair_order_counts"], {"B2_then_B3": 300, "B3_then_B2": 300})
        self.assertTrue(all(cell["observed_events"] == 12 for cell in cells))
        self.assertTrue(summary["fairness"]["logical_schedule_balanced"])
        self.assertEqual(set(summary["fairness"]["logical_position_counts"].values()), {150})

    def test_rotated_logical_order_is_validated_against_frozen_task(self) -> None:
        task = next(task for task in self.tasks.values() if task["logical_baseline_order"][0] == "B1")
        row = event(task, "B1")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, [row])
            summary, _ = collector.summarize(path, NOTEBOOK, "validation_only")
            self.assertEqual(summary["coverage"]["metadata_mismatch_count"], 0)
            row["logical_baseline_order"] = ["B0", "B1", "B2", "B3"]
            write(path, [row])
            summary, _ = collector.summarize(path, NOTEBOOK, "validation_only")
        self.assertEqual(summary["coverage"]["metadata_mismatch_count"], 1)
        self.assertIn("frozen_task_metadata_mismatch", summary["blockers"])

    def test_prompt_mismatch_blocks_fairness(self) -> None:
        task = next(iter(self.tasks.values()))
        rows = [event(task, "B2"), event(task, "B3")]
        rows[1]["prompt_sha256"] = "c" * 64
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, rows)
            summary, _ = collector.summarize(path, NOTEBOOK, "campaign")
        self.assertEqual(summary["fairness"]["prompt_hash_mismatch_count"], 1)
        self.assertIn("b2_b3_prompt_mismatch", summary["blockers"])

    def test_paired_effects_use_only_contract_eligible_pairs(self) -> None:
        tasks = list(self.tasks.values())[:3]
        rows = []
        for number, task in enumerate(tasks):
            base, tuned = event(task, "B2"), event(task, "B3")
            if number < 2:
                base["target_valid"] = False
                base["oracle_bearing"] = False
            rows.extend([base, tuned])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, rows)
            summary, _ = collector.summarize(path, NOTEBOOK, "validation_only")
        paired = summary["fairness"]["paired_outcomes"]
        self.assertEqual(paired["eligible_pair_count"], 3)
        self.assertEqual(sum(item["eligible_pair_count"] for item in paired["by_api_group"].values()), 3)
        self.assertEqual(sum(item["eligible_pair_count"] for item in paired["by_generation_seed"].values()), 3)
        target = paired["metrics"]["target_valid"]
        self.assertEqual(target["b2_only_pass"], 0)
        self.assertEqual(target["b3_only_pass"], 2)
        self.assertAlmostEqual(target["b3_minus_b2_paired_rate"], 2 / 3)
        self.assertEqual(target["mcnemar_exact_two_sided_p"], 0.5)

    def test_missing_raw_generation_blocks_campaign(self) -> None:
        task = next(iter(self.tasks.values()))
        row = event(task, "B0")
        row["raw_generation"] = False
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, [row])
            summary, _ = collector.summarize(path, NOTEBOOK, "campaign")
        self.assertEqual(summary["fairness"]["raw_generation_failure_count"], 1)
        self.assertIn("raw_generation_not_preserved", summary["blockers"])

    def test_impossible_oracle_state_is_rejected(self) -> None:
        row = event(next(iter(self.tasks.values())), "B2")
        row["target_valid"] = False
        with self.assertRaisesRegex(ValueError, "oracle-bearing event violates"):
            collector.validate_event(row, 1)

    def test_model_label_drift_is_reported(self) -> None:
        first, second = list(self.tasks.values())[:2]
        rows = [event(first, "B2"), event(second, "B2")]
        rows[1]["model"] = "different-base-model"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, rows)
            summary, _ = collector.summarize(path, NOTEBOOK, "campaign")
        self.assertEqual(summary["fairness"]["model_label_inconsistent_baselines"], ["B2"])
        self.assertIn("baseline_model_label_inconsistent", summary["blockers"])

    def test_multiple_signatures_requires_selection(self) -> None:
        task = next(iter(self.tasks.values()))
        rows = [event(task, "B0"), event(task, "B1", "6" * 64)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            write(path, rows)
            with self.assertRaisesRegex(ValueError, "multiple run signatures"):
                collector.summarize(path, NOTEBOOK, "validation_only")
            summary, _ = collector.summarize(path, NOTEBOOK, "validation_only", SIG)
        self.assertEqual(summary["coverage"]["observed_event_count"], 1)
        self.assertTrue(summary["fairness"]["same_harness_run_signature"])

    def test_interrupted_tail_is_ignored_but_blocks(self) -> None:
        task = next(iter(self.tasks.values()))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            path.write_text(json.dumps(event(task, "B0")) + "\n{" + '"partial":', encoding="utf-8")
            summary, _ = collector.summarize(path, NOTEBOOK, "validation_only")
        self.assertTrue(summary["source"]["truncated_tail_ignored"])
        self.assertIn("truncated_tail_ignored", summary["blockers"])

    def test_summary_schema(self) -> None:
        if jsonschema is None:
            self.skipTest("jsonschema not installed")
        schema = json.loads((HERE / "benchmark_result_summary.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        summary, _ = collector.summarize(SMOKE, NOTEBOOK, "validation_only")
        jsonschema.validate(summary, schema)
        index_schema = json.loads((HERE / "campaign_shard_index.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(index_schema)
        template = json.loads((HERE / "campaign_shards.template.json").read_text(encoding="utf-8"))
        jsonschema.validate(template, index_schema)

    def test_five_seed_shards_pass_verified_configuration_equivalence(self) -> None:
        signatures = {seed: str(index + 1) * 64 for index, seed in enumerate(self.manifest["generation_seeds"])}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            shards = []
            for seed in self.manifest["generation_seeds"]:
                signature = signatures[seed]
                seed_tasks = [task for task in self.tasks.values() if task["generation_seed"] == seed]
                events = directory / f"events-{seed}.jsonl"
                write(events, [event(task, baseline, signature) for task in seed_tasks for baseline in collector.BASELINES])
                run_manifest = {
                    "created_utc": "2026-07-08T00:00:00Z", "benchmark_id": self.manifest["benchmark_id"],
                    "manifest_sha256": self.manifest_hash, "documentation_sha256": "1" * 64,
                    "torch_version": "2.11.0+cu128", "torch_cuda": "12.8", "python": "3.12.13",
                    "packages": {"llama-cpp-python": "0.3.23"}, "gpu": "Tesla T4",
                    "base_model": self.frozen_run["base_model"],
                    "tuned_model": self.frozen_run["tuned_model"],
                    "decoding": self.frozen_run["decoding"],
                    "subprocess_timeout_s": self.frozen_run["subprocess_timeout_s"],
                    "selected_task_count": 120, "run_signature": signature, "event_log": str(events),
                }
                run_manifest_path = directory / f"manifest-{seed}.json"
                run_manifest_path.write_text(json.dumps(run_manifest), encoding="utf-8")
                executed = directory / f"executed-{seed}.ipynb"
                executed.write_bytes(NOTEBOOK.read_bytes())
                shards.append({
                    "generation_seed": seed, "run_signature": signature,
                    "events_path": events.name, "run_manifest_path": run_manifest_path.name,
                    "executed_notebook_path": executed.name,
                })
            index = directory / "campaign.json"
            index.write_text(json.dumps({
                "schema_version": "trdgl_campaign_shard_index_v1", "evidence_label": "campaign",
                "benchmark_id": self.manifest["benchmark_id"], "shards": shards,
            }), encoding="utf-8")
            rows, campaign = campaign_collector.collect_shards(index, NOTEBOOK)
            combined = directory / "combined.jsonl"
            write(combined, rows)
            summary, _ = collector.summarize(
                combined, NOTEBOOK, "campaign", allow_multiple_signatures=True,
                configuration_equivalence_verified=True,
            )
        self.assertEqual(len(rows), 2400)
        self.assertTrue(campaign["all_seeds_present"])
        self.assertTrue(campaign["all_shards_complete"])
        self.assertEqual(len(summary["source"]["all_run_signatures"]), 5)
        self.assertFalse(summary["fairness"]["same_harness_run_signature"])
        self.assertTrue(summary["fairness"]["harness_equivalence_verified"])
        self.assertTrue(summary["ready_for_paper_result"])

    def test_shard_manifest_drift_fails_closed(self) -> None:
        task = next(iter(self.tasks.values()))
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            shards = []
            for index_number, seed in enumerate(self.manifest["generation_seeds"][:2], 1):
                signature = str(index_number) * 64
                seed_task = next(t for t in self.tasks.values() if t["generation_seed"] == seed)
                events = directory / f"events-{seed}.jsonl"
                write(events, [event(seed_task, "B0", signature)])
                manifest = {
                    "created_utc": "2026-07-08T00:00:00Z",
                    "benchmark_id": self.manifest["benchmark_id"], "manifest_sha256": self.manifest_hash,
                    "documentation_sha256": "1" * 64, "torch_version": "2.11", "torch_cuda": "12.8",
                    "python": "3.12", "packages": {"llama-cpp-python": "0.3.23"}, "gpu": "T4",
                    "base_model": self.frozen_run["base_model"],
                    "tuned_model": self.frozen_run["tuned_model"],
                    "decoding": {
                        **self.frozen_run["decoding"],
                        "temperature": self.frozen_run["decoding"]["temperature"] + (index_number - 1),
                    },
                    "subprocess_timeout_s": self.frozen_run["subprocess_timeout_s"],
                    "selected_task_count": 120, "run_signature": signature, "event_log": str(events),
                }
                manifest_path = directory / f"manifest-{seed}.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                executed = directory / f"executed-{seed}.ipynb"
                executed.write_bytes(NOTEBOOK.read_bytes())
                shards.append({"generation_seed": seed, "run_signature": signature, "events_path": events.name, "run_manifest_path": manifest_path.name, "executed_notebook_path": executed.name})
            index_path = directory / "campaign.json"
            index_path.write_text(json.dumps({"schema_version": "trdgl_campaign_shard_index_v1", "evidence_label": "campaign", "benchmark_id": self.manifest["benchmark_id"], "shards": shards}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "decoding differs from frozen notebook"):
                campaign_collector.collect_shards(index_path, NOTEBOOK)

    def test_uniform_wrong_model_still_fails_frozen_contract(self) -> None:
        seed = self.manifest["generation_seeds"][0]
        signature = "4" * 64
        seed_task = next(t for t in self.tasks.values() if t["generation_seed"] == seed)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            events = directory / "events.jsonl"
            write(events, [event(seed_task, "B0", signature)])
            manifest = {
                "created_utc": "2026-07-08T00:00:00Z",
                "benchmark_id": self.manifest["benchmark_id"], "manifest_sha256": self.manifest_hash,
                "documentation_sha256": "1" * 64, "torch_version": "2.11", "torch_cuda": "12.8",
                "python": "3.12", "packages": {"llama-cpp-python": "0.3.23"}, "gpu": "T4",
                "base_model": {**self.frozen_run["base_model"], "revision": "wrong-but-uniform"},
                "tuned_model": self.frozen_run["tuned_model"], "decoding": self.frozen_run["decoding"],
                "subprocess_timeout_s": self.frozen_run["subprocess_timeout_s"],
                "selected_task_count": 120, "run_signature": signature, "event_log": str(events),
            }
            manifest_path = directory / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            executed = directory / "executed.ipynb"
            executed.write_bytes(NOTEBOOK.read_bytes())
            index_path = directory / "campaign.json"
            index_path.write_text(json.dumps({
                "schema_version": "trdgl_campaign_shard_index_v1", "evidence_label": "campaign",
                "benchmark_id": self.manifest["benchmark_id"], "shards": [{
                    "generation_seed": seed, "run_signature": signature, "events_path": events.name,
                    "run_manifest_path": manifest_path.name, "executed_notebook_path": executed.name,
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "base_model differs from frozen notebook"):
                campaign_collector.collect_shards(index_path, NOTEBOOK)

    def test_markdown_checkpoint_keeps_partial_boundary(self) -> None:
        summary, _ = collector.summarize(SMOKE, NOTEBOOK, "validation_only")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "checkpoint.md"
            collector.write_markdown(path, summary)
            report = path.read_text(encoding="utf-8")
        self.assertIn("Observed / expected events: **4 / 2400**", report)
        self.assertIn("Ready for paper result: **false**", report)
        self.assertIn("must not be described as a completed campaign", report)


if __name__ == "__main__":
    unittest.main()
