from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import collect_atlas_intervention as collector
import freeze_atlas_source as freezer

try:
    import jsonschema
except ImportError:
    jsonschema = None


HERE = Path(__file__).resolve().parent
EVENTS = HERE / "testdata/validation_events.jsonl"
ATLAS_AUDIT = HERE.parent / "vn_funnel/atlas_snapshot.json"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def make_verified_source(directory: Path, rows: list[dict]) -> tuple[Path, Path]:
    dataset = directory / "atlas.jsonl"
    dataset.write_text('{"issue_id":"validation"}\n', encoding="utf-8")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    for row in rows:
        if row["arm"] == "enabled":
            row["atlas_snapshot_sha256"] = digest
    manifest = {
        "schema_version": "trdgl_atlas_source_manifest_v1",
        "snapshot_id": "validation-snapshot",
        "evidence_label": "campaign",
        "dataset_file_name": dataset.name,
        "dataset_format": "jsonl",
        "dataset_sha256": digest,
        "dataset_bytes": dataset.stat().st_size,
        "record_count": 1,
        "created_utc": "2026-07-08T00:00:00Z",
        "created_by": "unit-test fixture",
        "source_system": "unit-test fixture",
        "export_command": "unit-test fixture; never a campaign command",
    }
    manifest_path = directory / "atlas.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return dataset, manifest_path


class AtlasInterventionTests(unittest.TestCase):
    def test_schemas_and_fixture_validate(self) -> None:
        rows = collector.load(EVENTS)
        self.assertEqual(len(rows), 4)
        if jsonschema is not None:
            event_schema = json.loads((HERE / "atlas_intervention_event.schema.json").read_text(encoding="utf-8"))
            summary_schema = json.loads((HERE / "atlas_intervention_summary.schema.json").read_text(encoding="utf-8"))
            source_schema = json.loads((HERE / "atlas_source_manifest.schema.json").read_text(encoding="utf-8"))
            bundle_schema = json.loads((HERE / "validation_bundle.schema.json").read_text(encoding="utf-8"))
            for schema in (event_schema, summary_schema, source_schema, bundle_schema):
                jsonschema.Draft202012Validator.check_schema(schema)
            for row in rows:
                jsonschema.validate(row, event_schema)
            jsonschema.validate(collector.summarize(EVENTS, ATLAS_AUDIT, [3407]), summary_schema)
            bundle = json.loads((HERE / "validation_output/validation_manifest.json").read_text(encoding="utf-8"))
            jsonschema.validate(bundle, bundle_schema)

    def test_validation_is_fail_closed_without_raw_atlas(self) -> None:
        result = collector.summarize(EVENTS, ATLAS_AUDIT, [3407, 7711, 12011, 19001, 27103])
        self.assertFalse(result["atlas_source"]["raw_atlas_dataset_present"])
        self.assertFalse(result["atlas_source"]["independent_manifest_present"])
        self.assertFalse(result["atlas_source"]["verified"])
        self.assertFalse(result["ready_for_paper_result"])
        self.assertIn("raw_atlas_dataset_absent", result["blockers"])
        self.assertIn("required_seeds_incomplete", result["blockers"])

    def test_pairs_share_model_decoding_harness_seed_and_base_input(self) -> None:
        result = collector.summarize(EVENTS, ATLAS_AUDIT, [3407])
        self.assertEqual(result["pairing"]["pair_count"], 2)
        self.assertEqual(result["pairing"]["incomplete_pairs"], [])
        self.assertEqual(result["pairing"]["pair_contract_mismatches"], [])
        self.assertTrue(result["pairing"]["single_harness"])
        self.assertTrue(result["pairing"]["single_model"])
        self.assertTrue(result["pairing"]["single_decoding_config"])
        self.assertTrue(result["pairing"]["pair_order_balanced"])

    def test_unknown_duplicate_verification_is_not_false_precision(self) -> None:
        result = collector.summarize(EVENTS, ATLAS_AUDIT, [3407])
        enabled = result["metrics"]["duplicate_triage"]["enabled"]
        self.assertEqual(enabled["duplicates_detected"], 1)
        self.assertEqual(enabled["duplicates_rejected"], 0)
        self.assertEqual(enabled["duplicate_verification_unknown"], 1)
        self.assertIsNone(enabled["retrieval_precision"])

    def test_unverified_duplicate_cannot_be_rejected(self) -> None:
        row = collector.load(EVENTS)[0]
        row["duplicate_verified"] = False
        row["duplicate_verification_method"] = "manual review"
        row["duplicate_verification_artifact_sha256"] = "6" * 64
        row["rejected_as_duplicate"] = True
        with self.assertRaisesRegex(ValueError, "lacks positive independent verification"):
            collector.validate(row, 1)

    def test_verified_raw_source_can_pass_campaign_gate(self) -> None:
        rows = collector.load(EVENTS)
        for row in rows:
            row["evidence_label"] = "campaign"
            row["experiment_id"] = "unit-test-campaign"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            dataset, manifest = make_verified_source(directory, rows)
            events = directory / "events.jsonl"
            write_jsonl(events, rows)
            result = collector.summarize(events, ATLAS_AUDIT, [3407], dataset, manifest)
            self.assertTrue(result["atlas_source"]["verified"])
            self.assertTrue(result["atlas_source"]["event_snapshot_matches_verified_dataset"])
            self.assertTrue(result["ready_for_paper_result"])
            self.assertEqual(result["blockers"], [])

    def test_tampered_raw_source_fails_closed(self) -> None:
        rows = collector.load(EVENTS)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            dataset, manifest = make_verified_source(directory, rows)
            dataset.write_text('{"issue_id":"tampered"}\n', encoding="utf-8")
            events = directory / "events.jsonl"
            write_jsonl(events, rows)
            result = collector.summarize(events, ATLAS_AUDIT, [3407], dataset, manifest)
            self.assertFalse(result["atlas_source"]["verified"])
            self.assertIn("atlas_source_verification_failed", result["blockers"])

    def test_disabled_arm_cannot_claim_retrieval(self) -> None:
        row = collector.load(EVENTS)[1]
        row["retrieval_performed"] = True
        with self.assertRaisesRegex(ValueError, "disabled arm"):
            collector.validate(row, 1)

    def test_guided_claim_requires_effective_prompt_change(self) -> None:
        row = collector.load(EVENTS)[2]
        row["effective_prompt_sha256"] = row["base_prompt_sha256"]
        with self.assertRaisesRegex(ValueError, "effective prompt intervention disagree"):
            collector.validate(row, 1)

    def test_known_duplicate_verification_requires_provenance(self) -> None:
        row = collector.load(EVENTS)[0]
        row["duplicate_verified"] = True
        with self.assertRaisesRegex(ValueError, "lacks method/artifact"):
            collector.validate(row, 1)

    def test_string_boolean_is_rejected_without_jsonschema(self) -> None:
        row = collector.load(EVENTS)[0]
        row["retrieval_performed"] = "true"
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            collector.validate(row, 1)

    def test_boolean_generation_seed_is_rejected(self) -> None:
        row = collector.load(EVENTS)[0]
        row["generation_seed"] = True
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            collector.validate(row, 1)

    def test_model_mismatch_is_reported_as_pair_confound(self) -> None:
        rows = collector.load(EVENTS)
        rows[1]["model_sha256"] = "5" * 64
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            write_jsonl(events, rows)
            result = collector.summarize(events, ATLAS_AUDIT, [3407])
            self.assertIn(["duplicate_triage", "candidate-1", "model_sha256"], result["pairing"]["pair_contract_mismatches"])
            self.assertIn("pair_contract_mismatches", result["blockers"])

    def test_duplicate_event_id_fails(self) -> None:
        first = EVENTS.read_text(encoding="utf-8").splitlines()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text(first + "\n" + first + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate event_id"):
                collector.load(path)

    def test_source_freezer_records_bytes_hash_count_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dataset = Path(temp) / "atlas.jsonl"
            dataset.write_text('{"issue_id":1}\n{"issue_id":2}\n', encoding="utf-8")
            manifest = freezer.build_manifest(
                dataset, "jsonl", "snapshot-real", "researcher", "issue-export",
                "python export_atlas.py", "2026-07-08T00:00:00Z",
            )
            frozen_bytes = dataset.read_bytes()
        self.assertEqual(manifest["record_count"], 2)
        self.assertEqual(manifest["dataset_bytes"], len(frozen_bytes))
        self.assertEqual(manifest["dataset_sha256"], hashlib.sha256(frozen_bytes).hexdigest())
        self.assertEqual(manifest["evidence_label"], "campaign")

    def test_source_freezer_rejects_empty_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dataset = Path(temp) / "atlas.jsonl"
            dataset.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                freezer.build_manifest(
                    dataset, "jsonl", "snapshot", "researcher", "issue-export",
                    "python export_atlas.py", "2026-07-08T00:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
