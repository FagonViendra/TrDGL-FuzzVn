from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import collect_artifact_manifest as collector

try:
    import jsonschema
except ImportError:  # The collector itself is standard-library only.
    jsonschema = None


HERE = Path(__file__).resolve().parent
PAPER = HERE.parents[1]
WORKSPACE = HERE.parents[2]
NOTEBOOK = PAPER / "experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb"


def args_for(output: Path, mode: str = "local_validation", run_dir: Path | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        mode=mode,
        workspace_root=WORKSPACE,
        notebook=NOTEBOOK,
        run_dir=run_dir,
        environment_lock=None,
        public_artifact_url_or_doi=None,
        artifact=[],
        output=output,
    )


class CollectorTests(unittest.TestCase):
    def test_schema_and_checked_validation_output_parse(self) -> None:
        schema = json.loads((HERE / "artifact_manifest.schema.json").read_text(encoding="utf-8"))
        output = json.loads((HERE / "validation_output/artifact_manifest.local.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], output["schema_version"])
        if jsonschema is not None:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(output, schema)
        collector.validate_manifest(output)

    def test_smoke_manifest_preserves_model_metadata_but_stays_incomplete(self) -> None:
        output = json.loads(
            (HERE / "validation_output/artifact_manifest.smoke.json").read_text(encoding="utf-8")
        )
        self.assertEqual(output["run"]["benchmark_id"], "trdgl_pytorch_120_v1")
        self.assertEqual(
            output["run"]["models"]["base"]["revision"],
            "3bb10d594514ef4edb7f3a65d41a7e4eb8c5767a",
        )
        self.assertEqual(
            output["run"]["models"]["tuned"]["revision"],
            "7e25063a37552beb994259e80c993b2edf41edbf",
        )
        self.assertIsNone(output["run"]["execution_command"])
        self.assertIn("run.execution_command", output["completeness"]["missing_fields"])
        self.assertFalse(output["completeness"]["ready_for_release"])

    def test_embedded_benchmark_is_hash_verified(self) -> None:
        benchmark = collector.extract_embedded_benchmark(NOTEBOOK)
        self.assertEqual(benchmark["api_count"], 120)
        self.assertEqual(benchmark["api_group_count"], 10)
        self.assertEqual(benchmark["generation_seeds"], [3407, 7711, 12011, 19001, 27103])
        self.assertEqual(benchmark["sha256"], "d9de15ca10bdd4abef2106c58b661197f69d1f278f87eec2b6eb56845f4facac")

    def test_local_validation_leaves_campaign_results_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = collector.collect(args_for(Path(directory) / "out.json"))
        self.assertEqual(manifest["evidence_label"], "local_validation")
        self.assertFalse(manifest["source_scope"]["run_environment_observed"])
        self.assertIsNone(manifest["run"]["run_signature"])
        self.assertIsNone(manifest["run"]["timing"]["duration_seconds"])
        self.assertIsNone(manifest["run"]["throughput"]["generations_per_hour"])
        self.assertFalse(manifest["completeness"]["ready_for_release"])

    def test_campaign_aggregates_one_signature_without_inventing_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            signature = "fixture-signature"
            run_manifest = {
                "run_signature": signature,
                "selected_task_count": 1,
                "torch_version": "fixture",
                "torch_cuda": "fixture",
                "python": "3.12",
                "gpu": "Fixture GPU",
                "packages": {},
            }
            (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")
            rows = []
            for index, baseline in enumerate(("B0", "B1", "B2", "B3")):
                rows.append({
                    "run_signature": signature, "task_id": "suite|torch.add|3407", "baseline": baseline,
                    "generation_seed": 3407,
                    "started_utc": f"2026-01-01T00:00:{index * 10:02d}+00:00",
                    "finished_utc": f"2026-01-01T00:00:{(index + 1) * 10:02d}+00:00",
                    "exit_code": None if baseline == "B1" else 0, "timeout": False,
                    "generation_seconds": 10 if baseline == "B1" else 2,
                    "subprocess_seconds": 0 if baseline == "B1" else 8,
                })
            with (run_dir / "events_latest.jsonl").open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            (run_dir / "baseline_summary.csv").write_text("baseline,count\nB0,1\n", encoding="utf-8")
            manifest = collector.collect(args_for(run_dir / "out.json", "campaign", run_dir))

        run = manifest["run"]
        self.assertEqual(run["run_signature"], signature)
        self.assertEqual(run["generation_seeds"], [3407])
        self.assertEqual(run["counts"]["generation_events"], 4)
        self.assertEqual(run["counts"]["identified_unique_events"], 4)
        self.assertEqual(run["counts"]["duplicate_identity_events"], 0)
        self.assertEqual(run["counts"]["missing_identity_events"], 0)
        self.assertEqual(run["counts"]["baseline_unique_events"], {"B0": 1, "B1": 1, "B2": 1, "B3": 1})
        self.assertEqual(run["counts"]["executed_tests"], 3)
        self.assertTrue(run["counts"]["selected_task_matrix_complete"])
        self.assertFalse(run["counts"]["full_benchmark_complete"])
        self.assertEqual(run["timing"]["duration_seconds"], 40.0)
        self.assertEqual(run["throughput"]["generations_per_hour"], 360.0)
        self.assertEqual(run["throughput"]["executed_tests_per_hour"], 270.0)
        self.assertIsNone(run["resources"]["gpu_hours"])
        self.assertEqual(run["resources"]["status"], "pending")

    def test_campaign_rejects_mixed_run_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "run_manifest.json").write_text(json.dumps({"run_signature": "a"}), encoding="utf-8")
            (run_dir / "events_latest.jsonl").write_text(
                json.dumps({"run_signature": "a"}) + "\n" + json.dumps({"run_signature": "b"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "one run signature"):
                collector.collect(args_for(run_dir / "out.json", "campaign", run_dir))

    def test_campaign_rejects_mismatched_benchmark_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "run_manifest.json").write_text(json.dumps({
                "run_signature": "a", "manifest_sha256": "0" * 64,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "benchmark hash does not match"):
                collector.collect(args_for(run_dir / "out.json", "campaign", run_dir))

    def test_duplicate_identity_cannot_complete_selected_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            signature = "fixture-signature"
            (run_dir / "run_manifest.json").write_text(json.dumps({
                "run_signature": signature, "selected_task_count": 1, "packages": {},
            }), encoding="utf-8")
            rows = [
                {"run_signature": signature, "baseline": baseline, "task_id": task_id,
                 "generation_seed": 3407}
                for baseline, task_id in (
                    ("B0", "task-a"), ("B0", "task-a"), ("B1", "task-a"), ("B2", "task-a")
                )
            ]
            (run_dir / "events_latest.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            manifest = collector.collect(args_for(run_dir / "out.json", "campaign", run_dir))
        counts = manifest["run"]["counts"]
        self.assertEqual(counts["generation_events"], 4)
        self.assertEqual(counts["identified_unique_events"], 3)
        self.assertEqual(counts["duplicate_identity_events"], 1)
        self.assertFalse(counts["selected_task_matrix_complete"])

    def test_full_matrix_requires_600_unique_events_per_baseline_and_five_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            signature = "full-fixture-signature"
            benchmark = collector.extract_embedded_benchmark(NOTEBOOK)
            (run_dir / "run_manifest.json").write_text(json.dumps({
                "run_signature": signature,
                "selected_task_count": 600,
                "benchmark_id": benchmark["benchmark_id"],
                "manifest_sha256": benchmark["sha256"],
                "packages": {},
            }), encoding="utf-8")
            seeds = benchmark["generation_seeds"]
            with (run_dir / "events_latest.jsonl").open("w", encoding="utf-8") as handle:
                for baseline in ("B0", "B1", "B2", "B3"):
                    for index in range(600):
                        handle.write(json.dumps({
                            "run_signature": signature,
                            "baseline": baseline,
                            "task_id": f"suite|api-{index // 5}|{seeds[index % 5]}",
                            "generation_seed": seeds[index % 5],
                        }) + "\n")
            manifest = collector.collect(args_for(run_dir / "out.json", "campaign", run_dir))
        counts = manifest["run"]["counts"]
        self.assertEqual(counts["generation_events"], 2400)
        self.assertEqual(counts["identified_unique_events"], 2400)
        self.assertEqual(counts["baseline_unique_events"], {baseline: 600 for baseline in ("B0", "B1", "B2", "B3")})
        self.assertTrue(counts["selected_task_matrix_complete"])
        self.assertTrue(counts["full_benchmark_complete"])

    def test_release_inputs_are_hashed_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "environment.lock"
            lock.write_text("fixture==1.0\n", encoding="utf-8")
            args = args_for(root / "out.json")
            args.environment_lock = lock
            args.public_artifact_url_or_doi = "https://doi.org/10.0000/example"
            manifest = collector.collect(args)
        self.assertTrue(manifest["release"]["environment_lock"]["present"])
        self.assertEqual(len(manifest["release"]["environment_lock"]["sha256"]), 64)
        self.assertEqual(manifest["release"]["environment_lock"]["path"], "external/environment.lock")
        self.assertEqual(
            manifest["release"]["public_artifact_url_or_doi"],
            "https://doi.org/10.0000/example",
        )
        self.assertNotIn("release.environment_lock", manifest["completeness"]["missing_fields"])
        self.assertNotIn("release.public_artifact_url_or_doi", manifest["completeness"]["missing_fields"])


if __name__ == "__main__":
    unittest.main()
