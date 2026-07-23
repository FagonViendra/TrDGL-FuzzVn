import json
import tempfile
import unittest
from pathlib import Path

import vn_funnel
import build_archive_report
import candidate_workflow


HERE = Path(__file__).resolve().parent


class FunnelTests(unittest.TestCase):
    def test_complete_fixture_counts(self):
        report = vn_funnel.summarize(vn_funnel.load_jsonl(HERE / "testdata" / "complete_events.jsonl"))
        counts = {row["stage"]: row["pass"] for row in report["funnel"]}
        self.assertEqual(counts["raw"], 3)
        self.assertEqual(counts["parseable"], 2)
        self.assertEqual(counts["oracle_bearing"], 1)
        self.assertEqual(counts["promoted"], 1)
        self.assertEqual(report["vn_gate"]["checked_non_duplicate"], 1)
        self.assertEqual(report["atlas_intervention"]["atlas_guided_true"], 1)

    def test_later_pass_after_failure_is_rejected(self):
        with self.assertRaises(vn_funnel.EvidenceError):
            vn_funnel.normalize({"event_id": "bad", "parses": False, "runnable": True})

    def test_promoted_requires_anomaly(self):
        with self.assertRaises(vn_funnel.EvidenceError):
            vn_funnel.normalize({"event_id": "bad", "promoted": True})

    def test_unknown_is_not_coerced_to_false(self):
        record = vn_funnel.normalize({"event_id": "partial", "parses": True})
        self.assertIsNone(record["stages"]["ast_pass"])

    def test_benchmark_runner_aliases_and_id_are_stable(self):
        event = {
            "run_signature": "sig-1",
            "task_id": "torch.add::3407",
            "baseline": "B2",
            "model": "base_gemma4_26b_q3km",
            "api": "torch.add",
            "generation_seed": 3407,
            "raw_output_sha256": "abc",
            "parseable": True,
            "ast_pass": True,
            "runnable": True,
            "target_valid": True,
            "oracle_bearing": False,
        }
        first = vn_funnel.normalize(event)
        second = vn_funnel.normalize(dict(event))
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(first["run_id"], "sig-1")
        self.assertEqual(first["model_revision"], "base_gemma4_26b_q3km")

    def test_ledger_validates(self):
        result = vn_funnel.validate_ledger(HERE / "candidate_ledger.jsonl")
        self.assertEqual(result["rows"], 5)
        self.assertEqual(result["status_counts"]["promoted"], {"no": 2, "pending": 3})
        self.assertEqual(result["evidence_level_counts"], {"paper_only": 3, "workspace_artifact": 2})

    def test_archive_report_keeps_missing_fields_missing(self):
        report = build_archive_report.build()
        self.assertEqual(report["funnel_field_coverage"]["raw"], {"campaigns_logged": 4, "campaigns_missing": 1})
        self.assertEqual(report["funnel_field_coverage"]["parseable"]["campaigns_logged"], 0)
        self.assertEqual(report["funnel_field_coverage"]["oracle_bearing"]["campaigns_logged"], 1)
        self.assertEqual(report["candidate_ledger"]["fully_promoted_candidates"], 0)
        self.assertEqual(len(report["candidate_ledger"]["artifact_files_audited"]), 5)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in report["candidate_ledger"]["artifact_files_audited"]))

    def test_atlas_source_audit_is_explicit(self):
        report = build_archive_report.build()
        atlas = report["atlas"]
        self.assertEqual(atlas["records"], 7275)
        self.assertEqual(atlas["source_audit"]["verification_status"], "internally_consistent_not_independently_recomputed")
        self.assertFalse(atlas["source_audit"]["raw_atlas_dataset_present_in_workspace"])
        self.assertIsNone(atlas["duplicate_candidates_detected"])
        self.assertIsNone(atlas["atlas_guided_candidates"])

    def test_round_trip_jsonl(self):
        rows = vn_funnel.load_jsonl(HERE / "testdata" / "complete_events.jsonl")
        normalized = [vn_funnel.normalize(row) for row in rows]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            vn_funnel.write_jsonl(path, normalized)
            self.assertEqual(vn_funnel.load_jsonl(path), normalized)

    def test_benchmark_import_does_not_infer_downstream_gates(self):
        event = {
            "run_signature": "smoke-sig",
            "baseline": "B3",
            "task_id": "trdgl_pytorch_120_v1|torch.tensor|3407",
            "api": "torch.tensor",
            "api_group": "tensor_creation",
            "generation_seed": 3407,
            "raw_generation": True,
            "parseable": True,
            "ast_pass": True,
            "runnable": True,
            "target_valid": True,
            "oracle_bearing": False,
            "raw_output_sha256": "abc",
            "error_labels": ["no_oracle"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "events_latest.jsonl"
            vn_funnel.write_jsonl(source, [event])
            manifest = vn_funnel.import_benchmark_events(source, root / "imported")
            imported = vn_funnel.load_jsonl(root / "imported" / "normalized_events.jsonl")[0]
            self.assertEqual(manifest["records"], 1)
            self.assertEqual(imported["run_id"], "smoke-sig")
            self.assertEqual(imported["source_sha256"], manifest["input_sha256"])
            self.assertEqual(imported["source_record_index"], 1)
            self.assertEqual(imported["importer_version"], vn_funnel.IMPORTER_VERSION)
            self.assertFalse(imported["stages"]["oracle_bearing"])
            for stage in ("reproducible", "non_duplicate", "minimized", "stable_nightly", "promoted"):
                self.assertIsNone(imported["stages"][stage])
                self.assertIsNone(imported["stage_evidence"][stage])
            report = json.loads((root / "imported" / "funnel_report.json").read_text(encoding="utf-8"))
            downstream = {row["stage"]: row for row in report["funnel"]}
            self.assertIsNone(downstream["reproducible"]["pass_rate_all_raw"])

    def test_benchmark_import_rejects_non_generation_record(self):
        event = {
            "run_signature": "bad-sig", "baseline": "B0", "task_id": "bad-task",
            "api": "torch.add", "api_group": "tensor", "generation_seed": 1,
            "raw_generation": False, "parseable": False, "ast_pass": False,
            "runnable": False, "target_valid": False, "oracle_bearing": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "events.jsonl"
            vn_funnel.write_jsonl(source, [event])
            with self.assertRaises(vn_funnel.EvidenceError):
                vn_funnel.import_benchmark_events(source, root / "out")

    def test_summary_rejects_duplicate_candidate_ids(self):
        row = vn_funnel.normalize({"event_id": "same", "parses": True})
        with self.assertRaises(vn_funnel.EvidenceError):
            vn_funnel.summarize([row, dict(row)])

    def test_summary_revalidates_normalized_input(self):
        row = vn_funnel.normalize({"event_id": "bad-normalized", "parses": True})
        row["stages"]["parseable"] = False
        row["stages"]["runnable"] = True
        with self.assertRaises(vn_funnel.EvidenceError):
            vn_funnel.summarize([row])

    def test_normalized_validator_fails_closed_on_missing_contract_field(self):
        row = vn_funnel.normalize({"event_id": "missing-provenance", "parses": True})
        del row["stage_evidence"]
        with self.assertRaises(vn_funnel.EvidenceError):
            vn_funnel.validate_normalized(row)

    def test_ledger_validator_rejects_malformed_row(self):
        bad = {
            "candidate_id": "bad",
            "candidate_family": "Bad candidate",
            "framework": "PyTorch",
            "reproduced": "maybe",
            "duplicate_checked": "pending",
            "minimized": "pending",
            "stable_tested": "pending",
            "nightly_tested": "pending",
            "promoted": "pending",
            "evidence_level": "paper_only",
            "artifact_paths": [],
            "evidence_source": "fixture",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            vn_funnel.write_jsonl(path, [bad])
            with self.assertRaises(vn_funnel.EvidenceError):
                vn_funnel.validate_ledger(path)

    def test_machine_readable_schemas_parse(self):
        for name in ("normalized_event.schema.json", "candidate_ledger.schema.json", "candidate_audit.schema.json"):
            schema = json.loads((HERE / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_validator_cli_returns_nonzero_for_duplicate_ids(self):
        row = vn_funnel.normalize({"event_id": "duplicate-cli", "parses": True})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.jsonl"
            vn_funnel.write_jsonl(path, [row, row])
            self.assertEqual(vn_funnel.main(["validate-normalized", str(path)]), 2)

    def _workflow_evidence(self, root, name):
        artifact = root / f"{name}.json"
        artifact.write_text(json.dumps({"step": name}), encoding="utf-8")
        return candidate_workflow.make_evidence(
            artifact, "pytest-fixture", "1.0", "2026-07-08T12:00:00+00:00", name
        )

    def test_workflow_imports_ledger_without_auto_verifying_legacy_states(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            self.assertEqual(candidate_workflow.import_ledger(HERE / "candidate_ledger.jsonl", log), 5)
            report = candidate_workflow.state_report(log)
            self.assertEqual(report["events"], 5)
            sparse = report["candidates"]["CAND-SPARSE-DESERIALIZE-001"]
            self.assertEqual(sparse["steps"]["reproducible"]["status"], "passed")
            self.assertFalse(sparse["steps"]["reproducible"]["verified_in_audit"])
            self.assertFalse(sparse["promoted"])

    def test_workflow_blocks_promotion_with_missing_or_legacy_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "audit.jsonl"
            candidate_workflow.import_ledger(HERE / "candidate_ledger.jsonl", log)
            evidence = self._workflow_evidence(root, "promotion")
            with self.assertRaises(candidate_workflow.WorkflowError):
                candidate_workflow.promote(log, "CAND-NVFP4-CONTRACTION-001", evidence)

    def test_workflow_rejects_illegal_repeat_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "audit.jsonl"
            candidate_workflow.import_ledger(HERE / "candidate_ledger.jsonl", log)
            evidence = self._workflow_evidence(root, "repro")
            candidate_workflow.update_step(log, "CAND-SPARSE-DESERIALIZE-001", "reproducible", "passed", evidence)
            with self.assertRaises(candidate_workflow.WorkflowError):
                candidate_workflow.update_step(log, "CAND-SPARSE-DESERIALIZE-001", "reproducible", "passed", evidence)

    def test_workflow_detects_audit_log_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            candidate_workflow.import_ledger(HERE / "candidate_ledger.jsonl", log)
            rows = vn_funnel.load_jsonl(log)
            rows[0]["candidate_family"] = "tampered"
            vn_funnel.write_jsonl(log, rows)
            with self.assertRaises(candidate_workflow.WorkflowError):
                candidate_workflow.replay(log)

    def test_workflow_detects_evidence_artifact_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "audit.jsonl"
            candidate_workflow.import_ledger(HERE / "candidate_ledger.jsonl", log)
            evidence = self._workflow_evidence(root, "artifact-tamper")
            candidate_workflow.update_step(log, "CAND-SPARSE-DESERIALIZE-001", "reproducible", "passed", evidence)
            Path(evidence["artifact_path"]).write_text("tampered", encoding="utf-8")
            with self.assertRaises(candidate_workflow.WorkflowError):
                candidate_workflow.replay(log, verify_artifacts=True)

    def test_workflow_promotes_only_after_five_audited_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "audit.jsonl"
            candidate_workflow.import_ledger(HERE / "candidate_ledger.jsonl", log)
            candidate_id = "CAND-TF-RAWOPS-CHECK-001"
            for step in candidate_workflow.STEPS:
                candidate_workflow.update_step(log, candidate_id, step, "passed", self._workflow_evidence(root, step))
            candidate_workflow.promote(log, candidate_id, self._workflow_evidence(root, "promotion"))
            report = candidate_workflow.state_report(log)
            self.assertTrue(report["candidates"][candidate_id]["promoted"])
            self.assertEqual(report["events"], 11)
            with self.assertRaises(candidate_workflow.WorkflowError):
                candidate_workflow.update_step(
                    log, candidate_id, "nightly_tested", "failed", self._workflow_evidence(root, "post-promotion")
                )


if __name__ == "__main__":
    unittest.main()
