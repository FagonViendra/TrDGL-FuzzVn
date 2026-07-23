from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import torch

import collect_numerical_oracle_results as collector
import run_numerical_oracle_protocol as runner

try:
    import jsonschema
except ImportError:
    jsonschema = None


HERE = Path(__file__).resolve().parent


class NumericalOracleTests(unittest.TestCase):
    def test_schema_and_local_events_validate(self) -> None:
        schema = json.loads((HERE / "numerical_oracle_event.schema.json").read_text(encoding="utf-8"))
        rows = collector.load(HERE / "validation_output/events.local.jsonl")
        self.assertEqual(len(rows), 24)
        if jsonschema is not None:
            jsonschema.Draft202012Validator.check_schema(schema)
            for row in rows:
                jsonschema.validate(row, schema)

    def test_local_summary_is_explicitly_incomplete(self) -> None:
        summary = collector.summarize(HERE / "validation_output/events.local.jsonl")
        self.assertEqual(summary["evidence_label"], "local_validation")
        self.assertEqual(summary["fixed_tolerances"], [1e-5, 1e-4, 1e-3])
        self.assertFalse(summary["completeness"]["all_factorial_dimensions_present"])
        self.assertFalse(summary["completeness"]["all_factorial_dimensions_measured"])
        self.assertFalse(summary["completeness"]["all_required_seeds_present"])
        self.assertFalse(summary["completeness"]["all_matched_threshold_cells_measured"])
        self.assertGreater(summary["completeness"]["missing_matched_threshold_cell_count"], 0)
        self.assertFalse(summary["completeness"]["certified_bound_present"])
        self.assertFalse(summary["completeness"]["ready_for_paper_result"])

    def test_ulp_is_zero_for_equal_values(self) -> None:
        values = torch.tensor([-1.0, -0.0, 0.0, 1.0], dtype=torch.float64)
        self.assertEqual(runner.ulp_max(values, values, torch.float64), 0)
        self.assertEqual(runner.ulp_max(values.float(), values.float(), torch.float32), 0)

    def test_compiled_preflight_failure_is_reused_without_execution(self) -> None:
        row = runner.measure(
            run_id="preflight-fixture", evidence_label="local_validation", seed=3407,
            device="cpu", mode="compiled", check_kind="forward", dtype_name="float32",
            control_kind="clean", tolerance_kind="fixed", tolerance=1e-4,
            certified_bound=None, certified_bound_source_sha256=None, inject_delta=2e-4,
            compiled_function=lambda _: self.fail("compiled function should not be retried"),
            compiled_probe={"status": "unsupported", "error": "backend unavailable"},
            env={"fixture": True},
        )
        self.assertEqual(row["status"], "unsupported")
        self.assertIn("compiled preflight", row["error"])

    def test_collector_rejects_duplicate_event_ids(self) -> None:
        first = (HERE / "validation_output/events.local.jsonl").read_text(encoding="utf-8").splitlines()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.jsonl"
            path.write_text(first + "\n" + first + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate event_id"):
                collector.load(path)

    def test_fixed_tolerance_requires_thresholds(self) -> None:
        row = json.loads((HERE / "validation_output/events.local.jsonl").read_text(encoding="utf-8").splitlines()[0])
        row["atol"] = None
        row["event_id"] = collector.expected_event_id(row)
        with self.assertRaisesRegex(ValueError, "lacks atol/rtol"):
            collector.validate(row, 1)

    def test_event_id_binds_full_experimental_design(self) -> None:
        row = json.loads((HERE / "validation_output/events.local.jsonl").read_text(encoding="utf-8").splitlines()[0])
        row["execution_backend"] = "tampered_backend"
        with self.assertRaisesRegex(ValueError, "event_id does not match"):
            collector.validate(row, 1)

    def test_certified_bound_requires_source_hash(self) -> None:
        row = json.loads((HERE / "validation_output/events.local.jsonl").read_text(encoding="utf-8").splitlines()[0])
        row.update(tolerance_kind="certified", atol=None, rtol=None, certified_bound=1e-6)
        row["event_id"] = collector.expected_event_id(row)
        with self.assertRaisesRegex(ValueError, "lacks bound/source hash"):
            collector.validate(row, 1)

    def test_nonfinite_and_negative_metrics_are_rejected(self) -> None:
        original = json.loads((HERE / "validation_output/events.local.jsonl").read_text(encoding="utf-8").splitlines()[0])
        for field, value, message in (
            ("abs_error_max", float("nan"), "must be finite"),
            ("duration_seconds", -1.0, "must be non-negative"),
        ):
            row = dict(original)
            row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                collector.validate(row, 1)

    def test_complete_matched_matrix_can_reach_paper_ready(self) -> None:
        template = json.loads(
            (HERE / "validation_output/events.local.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        rows = []
        for device in ("cpu", "cuda"):
            for mode in ("eager", "compiled"):
                for check in ("forward", "gradient"):
                    for dtype in ("float32", "float64"):
                        for seed in sorted(collector.EXPECTED_SEEDS):
                            for tolerance in sorted(collector.REQUIRED_TOLERANCES):
                                row = dict(template)
                                row.update(
                                    run_id="complete-fixture", evidence_label="campaign",
                                    device=device, execution_mode=mode,
                                    execution_backend="torch_compile_inductor" if mode == "compiled" else "torch_eager",
                                    check_kind=check, input_dtype=dtype, seed=seed,
                                    control_kind="clean", injected_delta=None,
                                    tolerance_kind="fixed", atol=tolerance, rtol=tolerance,
                                    certified_bound=None, certified_bound_source_sha256=None,
                                    status="pass", abs_error_max=0.0, rel_error_max=0.0,
                                    ulp_error_max=0, duration_seconds=0.01, error=None,
                                )
                                row["event_id"] = collector.expected_event_id(row)
                                rows.append(row)
        certified = dict(rows[0])
        certified.update(
            tolerance_kind="certified", atol=None, rtol=None, certified_bound=1e-6,
            certified_bound_source_sha256="a" * 64,
        )
        certified["event_id"] = collector.expected_event_id(certified)
        rows.append(certified)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "complete.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            summary = collector.summarize(path)
        self.assertEqual(len(rows), 241)
        self.assertTrue(summary["completeness"]["all_matched_threshold_cells_measured"])
        self.assertTrue(summary["completeness"]["all_required_seeds_present"])
        self.assertTrue(summary["completeness"]["ready_for_paper_result"])


if __name__ == "__main__":
    unittest.main()
