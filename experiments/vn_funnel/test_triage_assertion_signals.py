import json
import tempfile
import unittest
from pathlib import Path

from triage_assertion_signals import (
    build,
    classify_replay,
    extract_signals,
    is_assertion_signal,
    semantic_probes,
    validate_decisions,
)


def assertion_row(**overrides):
    row = {
        "run_signature": "run-1",
        "baseline": "B2",
        "task_id": "task-1",
        "api": "torch.reshape",
        "api_group": "shape",
        "generation_seed": 7,
        "raw_output_sha256": "a" * 64,
        "extracted_code": "assert False",
        "parseable": True,
        "target_call_present": True,
        "oracle_present": True,
        "fake_assertion": False,
        "exit_code": 1,
        "stderr": "Traceback\nAssertionError",
        "raw_generation": True,
        "ast_pass": True,
        "runnable": False,
        "target_valid": False,
        "oracle_bearing": False,
    }
    row.update(overrides)
    return row


class AssertionSignalTriageTests(unittest.TestCase):
    def test_signal_selection_is_fail_closed_and_ids_are_deterministic(self):
        row = assertion_row(_source_record_index=3)
        self.assertTrue(is_assertion_signal(row))
        self.assertFalse(is_assertion_signal({**row, "fake_assertion": True}))
        self.assertFalse(is_assertion_signal({**row, "target_call_present": False}))
        self.assertFalse(is_assertion_signal({**row, "stderr": "RuntimeError"}))

        first = extract_signals([row], "b" * 64)
        second = extract_signals([dict(row)], "b" * 64)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["source_record_index"], 3)
        self.assertIsNone(first[0]["anomaly_present"])
        self.assertTrue(all(value is None for value in first[0]["downstream_gate"].values()))

    def test_replay_classification_distinguishes_assertion_and_environment(self):
        self.assertEqual(classify_replay(0, "", False), "pass")
        self.assertEqual(classify_replay(1, "AssertionError", False), "assertion_failure")
        self.assertEqual(
            classify_replay(1, "Cannot find a working triton installation", False),
            "environment_unsupported",
        )
        self.assertEqual(classify_replay(None, "", True), "timeout")

    def test_decision_contract_blocks_unreviewed_promotion(self):
        signals = extract_signals([assertion_row(_source_record_index=1)], "b" * 64)
        sid = signals[0]["signal_id"]
        valid = {
            "signal_id": sid,
            "decision": "pending_pinned_environment_replay",
            "anomaly_present": None,
            "promoted": False,
            "candidate_id": "CAND-PENDING-1",
            "rationale": "same environment is unavailable",
            "evidence_refs": ["probe_results.json"],
        }
        result = validate_decisions(signals, [valid])
        self.assertEqual(result["anomaly_counts"]["unknown"], 1)
        self.assertEqual(result["provisional_candidate_count"], 1)
        with self.assertRaises(ValueError):
            validate_decisions(signals, [{**valid, "promoted": True}])
        with self.assertRaises(ValueError):
            validate_decisions(signals, [{**valid, "anomaly_present": True}])

    def test_semantic_probes_reject_generated_dense_references(self):
        probes = semantic_probes()
        self.assertEqual(probes["status"], "completed")
        for reshape in probes["reshape"]:
            self.assertFalse(reshape["generated_oracle_passes"])
            self.assertTrue(reshape["input_flatten_reference_passes"])
        sparse = probes["sparse_log_softmax"]
        self.assertFalse(sparse["generated_dense_zero_reference_passes"])
        self.assertTrue(sparse["explicit_sparse_reference_passes"])
        self.assertTrue(all(abs(value - 1.0) < 1e-6 for value in sparse["explicit_prob_sums"]))

    def test_build_preserves_unknown_anomaly_and_source_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "events.jsonl"
            source.write_text(json.dumps(assertion_row()) + "\n", encoding="utf-8")
            docs = root / "docs.json"
            docs.write_text(json.dumps({
                "torch.reshape": {"doc": "reshape"},
                "torch.sparse.log_softmax": {"doc": "log softmax"},
                "torch.sparse.softmax": {"doc": "unspecified entries are negative infinity"},
                "torch.compile": {"doc": "compile"},
            }), encoding="utf-8")
            output = root / "out"
            manifest = build(source, docs, output, set(), 1.0)
            self.assertEqual(manifest["input_records"], 1)
            self.assertEqual(manifest["assertion_signal_count"], 1)
            self.assertEqual(manifest["decision_evidence"]["anomaly_counts"]["unknown"], 1)
            self.assertEqual(manifest["decision_evidence"]["anomaly_counts"]["true"], 0)
            for name in manifest["outputs"] + ["triage_manifest.json"]:
                self.assertTrue((output / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
