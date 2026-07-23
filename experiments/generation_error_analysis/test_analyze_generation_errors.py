import csv
import json
import tempfile
import unittest
from pathlib import Path

from analyze_generation_errors import (
    CATEGORIES, LOADED_ANALYZER_SHA256, analyze, case_catalog_rows, classify_record,
    combined_campaign_view,
    coverage_rows, diagnostic_excerpt, group_error_rate_rows, harness_comparison_rows,
    harness_disagreement_rows,
    harness_expected_labels, integrity_rows, summarize,
    length_diagnostic_rows, seed_telemetry_rows, truncation_association_rows, wilson_interval,
)
from refresh_checkpoint import OutputLock, publish_staged_outputs, refresh_once
from review_validation import REVIEW_TOOL_SHA256, build_sample, cohen_kappa, compute_agreement


def record(code: str, **overrides):
    value = {
        "extracted_code": code,
        "api": "torch.add",
        "baseline": "B1",
        "api_group": "math",
        "generation_seed": 7,
        "finish_reason": "stop",
        "timeout": False,
        "exit_code": 0,
    }
    value.update(overrides)
    return value


class ClassificationTests(unittest.TestCase):
    def test_diagnostic_excerpt_prefers_last_exception_line(self):
        stderr = (
            "Traceback (most recent call last):\n"
            "RuntimeError: preliminary wrapper\n"
            + "backend fallback registration\n" * 30
            + "TypeError: argument 'indices' must be tuple, not Tensor\n"
        )
        self.assertEqual(
            diagnostic_excerpt(stderr),
            "TypeError: argument 'indices' must be tuple, not Tensor",
        )
        bounded = diagnostic_excerpt("x" * 4000)
        self.assertLessEqual(len(bounded), 240)
        self.assertIn(" ... ", bounded)

    def test_wilson_interval_requires_a_denominator(self):
        self.assertEqual(wilson_interval(0, 0), (None, None))
        low, high = wilson_interval(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=4)
        self.assertAlmostEqual(high, 0.7634, places=4)

    def test_group_rates_join_coverage_and_materialize_empty_denominators(self):
        summary = [{
            "aggregation": "baseline_group", "source": "checkpoint", "source_role": "campaign_checkpoint",
            "baseline": "B1", "api_group": "math", "category": "syntax_error", "n_total": 2,
            "n_known": 2, "n_true": 1, "n_false": 1, "n_unknown": 0,
        }]
        coverage = [{
            "source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B1",
            "api_group": "math", "observed_records": 2, "expected_records": 12,
            "missing_records": 10, "coverage_rate": 2 / 12,
        }]
        rows = group_error_rate_rows(summary, coverage)
        syntax = next(row for row in rows if row["category"] == "syntax_error")
        missing_import = next(row for row in rows if row["category"] == "missing_import")
        self.assertEqual((syntax["n_true"], syntax["n_known"], syntax["missing_records"]), (1, 2, 10))
        self.assertIsNotNone(syntax["wilson_95_low"])
        self.assertEqual(missing_import["n_known"], 0)
        self.assertIsNone(missing_import["wilson_95_low"])

    def test_truncation_association_is_within_baseline_and_preserves_unknowns(self):
        shared = {"source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B2"}
        classified = [
            {**shared, "truncated_generation": True, "syntax_error": True, "missing_oracle": None,
             "oracle_not_executed": None},
            {**shared, "truncated_generation": True, "syntax_error": False, "missing_oracle": True,
             "oracle_not_executed": False},
            {**shared, "truncated_generation": False, "syntax_error": False, "missing_oracle": False,
             "oracle_not_executed": False},
        ]
        coverage = [{
            **shared, "api_group": "__ALL__", "observed_records": 3, "expected_records": 120,
            "missing_records": 117, "coverage_rate": 3 / 120,
        }]
        rows = truncation_association_rows(classified, coverage)
        parseable = next(row for row in rows if row["outcome"] == "parseable")
        oracle = next(row for row in rows if row["outcome"] == "oracle_bearing")
        reachable = next(row for row in rows if row["outcome"] == "standalone_oracle_reachable")
        self.assertEqual((parseable["truncated_outcome_positive"], parseable["truncated_n"]), (1, 2))
        self.assertEqual(parseable["risk_difference_truncated_minus_nontruncated"], -0.5)
        self.assertEqual(oracle["unknown_outcome"], 1)
        self.assertEqual(oracle["risk_difference_truncated_minus_nontruncated"], -1.0)
        self.assertEqual(reachable["unknown_outcome"], 1)
        self.assertEqual(reachable["risk_difference_truncated_minus_nontruncated"], -1.0)

    def test_length_diagnostics_keep_finish_reason_and_missing_token_denominator(self):
        classified = [
            {"source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B2",
             "finish_reason": "length", "raw_token_count": 600, "generation_seconds": 2.0},
            {"source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B2",
             "finish_reason": "stop", "raw_token_count": 480, "generation_seconds": 1.0},
        ]
        coverage = [
            {"source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B2",
             "api_group": "__ALL__", "observed_records": 2, "expected_records": 120,
             "missing_records": 118},
            {"source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B3",
             "api_group": "__ALL__", "observed_records": 0, "expected_records": 120,
             "missing_records": 120},
        ]
        rows = length_diagnostic_rows(classified, coverage)
        b2_all = next(row for row in rows if row["baseline"] == "B2" and row["finish_reason"] == "__ALL__")
        b3_all = next(row for row in rows if row["baseline"] == "B3" and row["finish_reason"] == "__ALL__")
        self.assertEqual((b2_all["tokens_median"], b2_all["tokens_p95"]), (480.0, 600.0))
        self.assertEqual((b3_all["n_records"], b3_all["n_token_count_known"]), (0, 0))
        self.assertIsNone(b3_all["tokens_median"])

    def test_syntax_failure_does_not_turn_unobserved_checks_false(self):
        status, _ = classify_record(record("import torch\nx = torch.add(", exit_code=None))
        self.assertIs(status["syntax_error"], True)
        self.assertIsNone(status["wrong_or_missing_target_api"])
        self.assertIsNone(status["missing_import"])
        self.assertIsNone(status["missing_oracle"])

    def test_harness_default_fields_after_parse_failure_stay_unknown(self):
        expected = harness_expected_labels({
            "parseable": False, "target_call_present": False, "oracle_present": False,
            "fake_assertion": False, "timeout": False,
        })
        self.assertIs(expected["syntax_error"], True)
        self.assertIsNone(expected["wrong_or_missing_target_api"])
        self.assertIsNone(expected["missing_oracle"])
        self.assertIsNone(expected["fake_assertion"])
        self.assertIs(expected["timeout"], False)

    def test_harness_comparison_keeps_unknowns_out_of_agreement_denominator(self):
        base = {"source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B2"}
        rows = [
            {**base, "syntax_error": True, "harness_expected": {"syntax_error": True}},
            {**base, "syntax_error": None, "harness_expected": {"syntax_error": False}},
            {**base, "syntax_error": False, "harness_expected": {"syntax_error": None}},
            {**base, "syntax_error": False, "harness_expected": {"syntax_error": True}},
        ]
        audit = next(
            row for row in harness_comparison_rows(rows) if row["category"] == "syntax_error"
        )
        self.assertEqual((audit["n_comparable"], audit["n_agree"], audit["n_disagree"]), (2, 1, 1))
        self.assertEqual(audit["n_harness_true_analyzer_false"], 1)
        self.assertEqual(audit["n_harness_false_analyzer_true"], 0)
        self.assertEqual(audit["n_harness_unknown"], 1)
        self.assertEqual(audit["n_analyzer_unknown_given_harness_known"], 1)

    def test_missing_import_missing_oracle_and_uninvoked_target(self):
        status, _ = classify_record(record("def test_it():\n    x = torch.add(1, 2)\n"))
        self.assertIs(status["missing_import"], True)
        self.assertIs(status["missing_oracle"], True)
        self.assertIs(status["target_not_executed"], True)
        self.assertIs(status["wrong_or_missing_target_api"], False)

    def test_fake_and_broad_swallowing(self):
        code = """import torch
try:
    result = torch.add(1, 2)
    assert result == result
except Exception:
    pass
"""
        status, _ = classify_record(record(code, oracle_present=True))
        self.assertIs(status["fake_assertion"], True)
        self.assertIs(status["broad_exception_swallowing"], True)
        self.assertIs(status["missing_oracle"], False)

    def test_shape_dtype_runtime_is_not_other_runtime(self):
        status, _ = classify_record(record(
            "import torch\ntorch.add(torch.ones(2), torch.ones(3))",
            exit_code=1,
            stderr="RuntimeError: The size of tensor a (2) must match the size of tensor b (3)",
        ))
        self.assertIs(status["shape_or_dtype_error"], True)
        self.assertIs(status["runtime_error_other"], False)

    def test_wrong_api_and_other_runtime(self):
        status, _ = classify_record(record(
            "import torch\ntorch.subtract(2, 1)",
            exit_code=1,
            stderr="RuntimeError: simulated backend failure",
        ))
        self.assertIs(status["wrong_or_missing_target_api"], True)
        self.assertIs(status["runtime_error_other"], True)
        self.assertIs(status["shape_or_dtype_error"], False)

    def test_runtime_subtaxonomy_is_specific(self):
        cases = (
            ("NameError: name 'result' is not defined", "undefined_name_error"),
            ("TypeError: add() got an unexpected keyword argument 'axis'", "argument_signature_error"),
            ("TypeError: argument 'indices' must be tuple of Tensors, not Tensor", "argument_signature_error"),
            ("ModuleNotFoundError: No module named 'made_up'", "dependency_import_error"),
            ("RuntimeError: index out of column bound: 2 not between 1 and 2", "index_or_bounds_error"),
            ("AssertionError", "assertion_failure"),
        )
        for stderr, category in cases:
            with self.subTest(category=category):
                status, _ = classify_record(record(
                    "import torch\ntorch.add(1, 2)", exit_code=1, stderr=stderr
                ))
                self.assertIs(status[category], True)
                self.assertIs(status["runtime_error_other"], False)

    def test_expected_dimension_comma_got_is_shape_error(self):
        status, _ = classify_record(record(
            "import torch\ntorch.add(1, 2)", exit_code=1,
            stderr="RuntimeError: Expected dim 0 size 3, got 5",
        ))
        self.assertIs(status["shape_or_dtype_error"], True)
        self.assertIs(status["runtime_error_other"], False)

    def test_argument_instance_error_is_not_mislabeled_shape_dtype(self):
        status, _ = classify_record(record(
            "import torch\ntorch.add(1, 2)", exit_code=1,
            stderr="ValueError: Expected `mod` to be an instance of `torch.nn.Module`, got <class 'function'>.",
        ))
        self.assertIs(status["argument_signature_error"], True)
        self.assertIs(status["shape_or_dtype_error"], False)
        self.assertIs(status["runtime_error_other"], False)

    def test_real_vs_complex_input_is_dtype_error(self):
        status, _ = classify_record(record(
            "import torch\ntorch.add(1, 2)", exit_code=1,
            stderr="RuntimeError: ihfft expects a real input tensor, but got ComplexFloat",
        ))
        self.assertIs(status["shape_or_dtype_error"], True)
        self.assertIs(status["runtime_error_other"], False)

    def test_undefined_local_is_not_mislabeled_missing_import(self):
        status, _ = classify_record(record(
            "import torch\ntorch.add(1, 2)\nprint(result)",
            exit_code=1,
            stderr="NameError: name 'result' is not defined",
        ))
        self.assertIs(status["undefined_name_error"], True)
        self.assertIs(status["missing_import"], False)

    def test_import_in_unrelated_or_dead_scope_does_not_bind_module_alias(self):
        unrelated, evidence = classify_record(record(
            "def helper():\n    import torch\n"
            "result = torch.add(1, 2)\n"
        ))
        self.assertIs(unrelated["missing_import"], True)
        self.assertIn("module:torch", evidence["missing_import"])

        dead, evidence = classify_record(record(
            "if False:\n    import torch\n"
            "result = torch.add(1, 2)\n"
        ))
        self.assertIs(dead["missing_import"], True)
        self.assertIn("module:torch", evidence["missing_import"])

    def test_module_import_is_visible_inside_top_level_function(self):
        status, _ = classify_record(record(
            "import torch\n"
            "def helper():\n    return torch.add(1, 2)\n"
            "helper()\n"
        ))
        self.assertIs(status["missing_import"], False)

    def test_setup_resource_and_reproducibility_labels(self):
        setup, _ = classify_record(record(
            "import torch\ntorch.add(1, 2)", exit_code=1,
            stderr="RuntimeError: Found no NVIDIA driver on your system",
            reproducible=False,
        ))
        self.assertIs(setup["setup_or_environment_error"], True)
        self.assertIs(setup["nondeterministic_failure"], True)
        self.assertIs(setup["runtime_error_other"], False)
        oom, _ = classify_record(record(
            "import torch\ntorch.add(1, 2)", exit_code=1,
            stderr="torch.OutOfMemoryError: CUDA out of memory",
        ))
        self.assertIs(oom["resource_exhaustion"], True)
        self.assertIs(oom["runtime_error_other"], False)

    def test_nondeterminism_is_unknown_without_replays(self):
        status, _ = classify_record(record("import torch\ntorch.add(1, 2)"))
        self.assertIsNone(status["nondeterministic_failure"])

    def test_missing_api_name_is_unknown_not_wrong(self):
        status, _ = classify_record(record("import torch\ntorch.add(1, 2)", api=None))
        self.assertIsNone(status["wrong_or_missing_target_api"])
        self.assertIsNone(status["target_not_executed"])

    def test_ast_oracle_can_correct_false_default_field(self):
        status, _ = classify_record(record(
            "import torch\nassert torch.add(1, 2) == 3", oracle_present=False
        ))
        self.assertIs(status["missing_oracle"], False)

    def test_oracle_bearing_is_separate_from_standalone_reachability(self):
        unreachable, _ = classify_record(record(
            "import torch\ndef test_it():\n    x = torch.add(1, 2)\n    assert x == 3\n"
        ))
        self.assertIs(unreachable["missing_oracle"], False)
        self.assertIs(unreachable["oracle_not_executed"], True)

        reachable, _ = classify_record(record(
            "import torch\ndef helper():\n    x = torch.add(1, 2)\n    assert x == 3\n"
            "def main():\n    helper()\nmain()\n"
        ))
        self.assertIs(reachable["missing_oracle"], False)
        self.assertIs(reachable["oracle_not_executed"], False)

        unresolved, _ = classify_record(record(
            "import torch\nclass Test:\n    def check(self):\n        assert torch.add(1, 2) == 3\n"
        ))
        self.assertIs(unresolved["missing_oracle"], False)
        self.assertIsNone(unresolved["oracle_not_executed"])

    def test_oracle_reachability_follows_aliased_helper_chain(self):
        status, evidence = classify_record(record(
            "import torch\n"
            "def check():\n    assert torch.add(1, 2) == 3\n"
            "def main():\n    alias()\n"
            "alias = check\nmain()\n"
        ))
        self.assertIs(status["oracle_not_executed"], False)
        self.assertIn("reachable", evidence["oracle_not_executed"])

    def test_target_execution_follows_transitive_helper_chain(self):
        status, evidence = classify_record(record(
            "import torch\n"
            "def invoke():\n    return torch.add(1, 2)\n"
            "def main():\n    return invoke()\n"
            "main()\n"
        ))
        self.assertIs(status["target_not_executed"], False)
        self.assertIn("reachable", evidence["target_not_executed"])

        unreachable, _ = classify_record(record(
            "import torch\n"
            "def invoke():\n    return torch.add(1, 2)\n"
            "def main():\n    return invoke()\n"
        ))
        self.assertIs(unreachable["target_not_executed"], True)

    def test_literal_dead_branches_do_not_make_target_or_oracle_reachable(self):
        status, evidence = classify_record(record(
            "import torch\n"
            "def test_it():\n"
            "    if False:\n"
            "        value = torch.add(1, 2)\n"
            "        assert value == 3\n"
            "test_it()\n"
        ))
        # The syntax-bearing oracle still exists, but standalone execution
        # cannot reach either it or the target call.
        self.assertIs(status["missing_oracle"], False)
        self.assertIs(status["oracle_not_executed"], True)
        self.assertIs(status["target_not_executed"], True)
        self.assertIn("unreachable", evidence["oracle_not_executed"])

    def test_unknown_branch_remains_conservatively_reachable(self):
        status, _ = classify_record(record(
            "import torch, os\n"
            "if os.getenv('RUN'):\n"
            "    value = torch.add(1, 2)\n"
            "    assert value == 3\n"
        ))
        self.assertIs(status["oracle_not_executed"], False)
        self.assertIs(status["target_not_executed"], False)

    def test_aliased_assert_close_is_a_recognized_oracle(self):
        status, _ = classify_record(record(
            "import torch\nimport torch.testing as tt\nx = torch.add(1, 2)\ntt.assert_close(x, torch.tensor(3))"
        ))
        self.assertIs(status["missing_oracle"], False)
        self.assertIs(status["oracle_not_executed"], False)

    def test_raise_assertion_error_and_common_testing_helpers_are_oracles(self):
        cases = (
            "import torch\nx = torch.add(1, 2)\nif x != 3:\n    raise AssertionError('wrong')",
            "import torch\ntorch._assert(torch.add(1, 2) == 3, 'wrong')",
            "import numpy.testing as nt\nimport torch\nnt.assert_array_equal(torch.add(1, 2), 3)",
        )
        for code in cases:
            with self.subTest(code=code):
                status, _ = classify_record(record(code, oracle_present=False))
                self.assertIs(status["missing_oracle"], False)
                self.assertIs(status["oracle_not_executed"], False)

    def test_aliased_self_comparison_oracle_is_fake(self):
        status, evidence = classify_record(record(
            "import torch\nfrom torch.testing import assert_close as check\n"
            "x = torch.add(1, 2)\ncheck(x, x)",
            oracle_present=False,
        ))
        self.assertIs(status["missing_oracle"], False)
        self.assertIs(status["fake_assertion"], True)
        self.assertIn("itself", evidence["fake_assertion"])

    def test_literal_and_self_comparing_helper_oracles_are_fake(self):
        cases = (
            "import torch\ntorch.add(1, 2)\ntorch._assert(True, 'always')",
            "import torch\nimport numpy.testing as nt\nx = torch.add(1, 2)\nnt.assert_equal(x, x)",
            "import torch\nfrom unittest import TestCase\nx = torch.add(1, 2)\nTestCase().assertTrue(False)",
        )
        for code in cases:
            with self.subTest(code=code):
                status, _ = classify_record(record(code, oracle_present=False))
                self.assertIs(status["missing_oracle"], False)
                self.assertIs(status["fake_assertion"], True)

    def test_import_and_callable_aliases_resolve_target(self):
        for code in (
            "import torch as pt\nassert pt.add(1, 2) == 3",
            "import torch.nn.functional\nassert torch.nn.functional.relu(torch.tensor([-1.])).item() == 0",
            "from torch import add as plus\nassert plus(1, 2) == 3",
            "import torch\nop = torch.add\nassert op(1, 2) == 3",
            "from torch import *\nassert add(1, 2) == 3",
            "import torch\nassert getattr(torch, 'add')(1, 2) == 3",
        ):
            with self.subTest(code=code):
                api = "torch.nn.functional.relu" if "functional.relu" in code else "torch.add"
                status, _ = classify_record(record(code, api=api, target_call_present=False))
                self.assertIs(status["wrong_or_missing_target_api"], False)

    def test_target_alias_evidence_explains_harness_disagreement(self):
        status, evidence = classify_record(record(
            "import torch.nn.functional as F\nF.relu(torch.tensor([-1.]))",
            api="torch.nn.functional.relu", target_call_present=False,
        ))
        self.assertIs(status["wrong_or_missing_target_api"], False)
        self.assertIn("F.relu -> torch.nn.functional.relu", evidence["wrong_or_missing_target_api"])

    def test_wrong_api_evidence_exposes_method_and_inplace_near_misses(self):
        status, evidence = classify_record(record(
            "import torch\nx = torch.randn(2, 3)\ny = x.permute(1, 0)",
            api="torch.permute", target_call_present=False,
        ))
        self.assertIs(status["wrong_or_missing_target_api"], True)
        self.assertIn("x.permute (same terminal name on a different receiver)", evidence["wrong_or_missing_target_api"])

        status, evidence = classify_record(record(
            "import torch\nx = torch.zeros(2)\nx.index_add_(0, torch.tensor([0]), torch.ones(1))",
            api="torch.index_add", target_call_present=False,
        ))
        self.assertIs(status["wrong_or_missing_target_api"], True)
        self.assertIn("in-place/non-in-place name variant", evidence["wrong_or_missing_target_api"])

    def test_allclose_self_comparison_is_fake(self):
        status, _ = classify_record(record(
            "import torch\nx = torch.add(1, 2)\nassert torch.allclose(x, x)", oracle_present=True
        ))
        self.assertIs(status["fake_assertion"], True)

    def test_literal_assertions_are_fake_whether_they_pass_or_fail(self):
        for expression in ("True", "False", "not False", "1 < 2", "1 == 2"):
            with self.subTest(expression=expression):
                status, _ = classify_record(record(
                    f"import torch\ntorch.add(1, 2)\nassert {expression}", oracle_present=True
                ))
                self.assertIs(status["fake_assertion"], True)

    def test_tuple_broad_handler_is_detected(self):
        status, _ = classify_record(record(
            "import torch\ntry:\n torch.add(1, 2)\nexcept (ValueError, Exception):\n pass"
        ))
        self.assertIs(status["broad_exception_swallowing"], True)

    def test_summary_preserves_unknown_denominator(self):
        base = {"source": "x", "source_role": "campaign_checkpoint", "baseline": "B1", "api_group": "g"}
        rows = []
        for value in (True, False, None):
            item = dict(base)
            item.update({category: False for category in CATEGORIES})
            item["syntax_error"] = value
            rows.append(item)
        summary = summarize(rows)
        target = next(r for r in summary if r["aggregation"] == "baseline" and r["category"] == "syntax_error")
        self.assertEqual((target["n_total"], target["n_known"], target["n_unknown"]), (3, 2, 1))
        self.assertEqual(target["failure_rate_known"], 0.5)

    def test_summary_exposes_seed_baseline_group_aggregation(self):
        item = {
            "source": "campaign", "source_role": "campaign_checkpoint", "generation_seed": 3407,
            "baseline": "B2", "api_group": "math", **{category: False for category in CATEGORIES},
        }
        rows = summarize([item])
        seed_row = next(
            row for row in rows
            if row["aggregation"] == "seed_baseline_group" and row["category"] == "syntax_error"
        )
        self.assertEqual(
            (seed_row["generation_seed"], seed_row["baseline"], seed_row["api_group"]),
            (3407, "B2", "math"),
        )

    def test_seed_telemetry_uses_only_valid_pairs_without_imputation(self):
        shared = {
            "source": "campaign", "source_role": "campaign_checkpoint", "generation_seed": 3407,
            "baseline": "B2", "subprocess_seconds": 0.5,
        }
        rows = seed_telemetry_rows([
            {**shared, "task_id": "one", "raw_token_count": 20, "generation_seconds": 2.0},
            {**shared, "task_id": "two", "raw_token_count": 10, "generation_seconds": None},
        ])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["raw_records"], row["unique_tasks"], row["n_token_generation_pairs"]), (2, 2, 1))
        self.assertEqual(row["aggregate_tokens_per_generation_second"], 10.0)


class EndToEndTests(unittest.TestCase):
    def test_combined_campaign_scales_expectation_by_distinct_seed(self):
        shared = {
            "source_role": "campaign_checkpoint", "baseline": "B1", "api_group": "math",
            **{category: False for category in CATEGORIES},
        }
        classified = [
            {**shared, "source": "seed7", "generation_seed": 7, "task_id": "suite|torch.add|7"},
            {**shared, "source": "seed8", "generation_seed": 8, "task_id": "suite|torch.add|8"},
        ]
        summary, coverage, group_rates, metadata = combined_campaign_view(classified, 120, 12)
        b1 = next(row for row in coverage if row["baseline"] == "B1" and row["api_group"] == "__ALL__")
        self.assertEqual(metadata["generation_seeds"], ["7", "8"])
        self.assertEqual((b1["observed_records"], b1["expected_records"], b1["missing_records"]), (2, 240, 238))
        self.assertTrue(summary)
        self.assertTrue(group_rates)

        duplicate = [classified[0], {**classified[0], "source": "seed7_duplicate"}]
        _, duplicate_coverage, _, duplicate_metadata = combined_campaign_view(duplicate, 120, 12)
        b1_duplicate = next(
            row for row in duplicate_coverage if row["baseline"] == "B1" and row["api_group"] == "__ALL__"
        )
        self.assertEqual(duplicate_metadata["shard_count"], 1)
        self.assertEqual((b1_duplicate["observed_records"], b1_duplicate["duplicate_records"]), (1, 1))

        mixed = [classified[0], {**classified[0], "source": "legacy", "generation_seed": None, "task_id": "legacy"}]
        _, mixed_coverage, _, mixed_metadata = combined_campaign_view(mixed, 120, 12)
        mixed_b1 = next(
            row for row in mixed_coverage if row["baseline"] == "B1" and row["api_group"] == "__ALL__"
        )
        self.assertEqual(mixed_metadata["unknown_seed_sources"], ["legacy"])
        self.assertEqual(mixed_metadata["shard_count"], 2)
        self.assertEqual(mixed_b1["expected_records"], 240)

    def test_coverage_uses_unique_task_ids_not_raw_rows(self):
        base = {
            "source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B1",
            "api_group": "math",
        }
        rows = [
            {**base, "task_id": "suite|torch.add|7"},
            {**base, "task_id": "suite|torch.add|7"},
            {**base, "task_id": "suite|torch.mul|7"},
            {**base, "task_id": None},
        ]
        coverage = coverage_rows(
            rows, [{"label": "checkpoint", "role": "campaign_checkpoint"}], 120, 12
        )
        overall = next(
            row for row in coverage if row["baseline"] == "B1" and row["api_group"] == "__ALL__"
        )
        self.assertEqual(overall["raw_records"], 4)
        self.assertEqual(overall["observed_records"], 2)
        self.assertEqual(overall["duplicate_records"], 1)
        self.assertEqual(overall["unidentified_records"], 1)
        self.assertEqual(overall["missing_records"], 118)

    def test_kappa_is_undefined_for_constant_marginals(self):
        agreement, kappa = cohen_kappa([("true", "true"), ("true", "true")])
        self.assertEqual(agreement, 1.0)
        self.assertIsNone(kappa)

    def test_case_catalog_selects_one_traceable_example_per_category(self):
        rows = []
        for index in (2, 1):
            item = {
                "source": "checkpoint", "source_role": "campaign_checkpoint", "source_sha256": "abc",
                "source_record_index": index, "baseline": "B1", "task_id": f"task-{index}",
                "api_group": "math", "api": "torch.add", "generation_seed": 7,
                "exit_code": 1, "stderr_excerpt": "RuntimeError: example",
                "raw_output_sha256": f"raw-{index}", "evidence": {name: "why" for name in CATEGORIES},
            }
            item.update({name: False for name in CATEGORIES})
            item["missing_oracle"] = True
            rows.append(item)
        catalog = case_catalog_rows(rows)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["source_record_index"], 1)
        self.assertEqual(catalog[0]["raw_output_sha256"], "raw-1")
        self.assertEqual(catalog[0]["stderr_excerpt"], "RuntimeError: example")

    def test_integrity_audit_exposes_duplicate_identity_without_dropping_records(self):
        base = {
            "source": "checkpoint", "source_role": "campaign_checkpoint", "baseline": "B1",
            "task_id": "suite|torch.add|7", "run_signature": "run-a", "generation_seed": 7,
        }
        rows = [dict(base), dict(base), {**base, "baseline": "BX", "task_id": None}]
        audit = integrity_rows(
            rows,
            [{"label": "checkpoint", "role": "campaign_checkpoint"}],
        )[0]
        self.assertEqual(audit["records"], 3)
        self.assertEqual(audit["duplicate_task_baseline_records"], 1)
        self.assertEqual(audit["missing_task_id_records"], 1)
        self.assertEqual(audit["unexpected_baseline_records"], 1)

    def test_row_level_harness_disagreement_is_traceable(self):
        statuses, evidence = classify_record(record(
            "import torch.nn.functional as F\nF.relu(torch.tensor([-1.]))",
            api="torch.nn.functional.relu", target_call_present=False, parseable=True,
        ))
        item = {
            "source": "checkpoint", "source_role": "campaign_checkpoint", "source_sha256": "abc",
            "source_record_index": 9, "baseline": "B1", "task_id": "task-9", "api_group": "nn",
            "api": "torch.nn.functional.relu", "generation_seed": 7, "raw_output_sha256": "raw-9",
            "harness_expected": harness_expected_labels({"parseable": True, "target_call_present": False}),
            "evidence": evidence, **statuses,
        }
        disagreements = harness_disagreement_rows([item])
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0]["category"], "wrong_or_missing_target_api")
        self.assertIn("F.relu -> torch.nn.functional.relu", disagreements[0]["analyzer_evidence"])

    def test_output_lock_does_not_remove_a_successor_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            with OutputLock(output) as lock:
                lock.path.write_text("pid=successor nonce=new utc=now\n", encoding="utf-8")
            self.assertEqual(
                (output / ".refresh.lock").read_text(encoding="utf-8"),
                "pid=successor nonce=new utc=now\n",
            )

    def test_staged_publish_keeps_manifest_when_batch_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, stage = root / "out", root / "stage"
            output.mkdir()
            stage.mkdir()
            (output / "analysis_manifest.json").write_text("old", encoding="utf-8")
            (stage / "one.txt").write_text("new", encoding="utf-8")
            (stage / "analysis_manifest.json").write_text("new manifest", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                publish_staged_outputs(stage, output, ["one.txt", "missing.txt"])
            self.assertEqual((output / "analysis_manifest.json").read_text(encoding="utf-8"), "old")
            self.assertFalse((output / "one.txt").exists())

    def test_outputs_and_absent_baseline_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "checkpoint.jsonl"
            source.write_text(json.dumps(record("import torch\nassert torch.add(1, 2) == 3")) + "\n", encoding="utf-8")
            output = root / "out"
            manifest = analyze([source], output, expected_per_baseline=120)
            self.assertEqual(manifest["classified_records"], 1)
            self.assertEqual(manifest["analyzer_sha256"], LOADED_ANALYZER_SHA256)
            for name in manifest["outputs"] + ["analysis_manifest.json"]:
                self.assertTrue((output / name).is_file(), name)
            self.assertIn(
                "Deterministic audit pointers",
                (output / "failure_case_catalog.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((output / "detector_harness_disagreements.csv").is_file())
            self.assertTrue((output / "length_diagnostics.csv").is_file())
            self.assertTrue((output / "campaign_combined_coverage.csv").is_file())
            with (output / "event_classification.csv").open(encoding="utf-8", newline="") as handle:
                event = next(csv.DictReader(handle))
            self.assertEqual(event["exit_code"], "0")
            self.assertEqual(event["stderr_excerpt"], "")
            coverage = json.loads((output / "coverage_summary.json").read_text(encoding="utf-8"))["rows"]
            b3 = next(r for r in coverage if r["baseline"] == "B3" and r["api_group"] == "__ALL__")
            self.assertEqual((b3["observed_records"], b3["missing_records"]), (0, 120))
            group_rates = json.loads((output / "group_error_rates.json").read_text(encoding="utf-8"))["rows"]
            b3_syntax = next(
                r for r in group_rates
                if r["baseline"] == "B3" and r["api_group"] == "math" and r["category"] == "syntax_error"
            )
            self.assertEqual((b3_syntax["n_known"], b3_syntax["missing_records"]), (0, 12))
            self.assertIsNone(b3_syntax["wilson_95_low"])
            associations = json.loads(
                (output / "truncation_associations.json").read_text(encoding="utf-8")
            )["rows"]
            b3_parse = next(r for r in associations if r["baseline"] == "B3" and r["outcome"] == "parseable")
            self.assertEqual((b3_parse["n_total"], b3_parse["missing_records"]), (0, 120))
            self.assertIsNone(b3_parse["risk_difference_truncated_minus_nontruncated"])
            self.assertIn("Wilson 95", (output / "validation_group_rates.tex").read_text(encoding="utf-8"))
            report = (output / "validation_report.md").read_text(encoding="utf-8")
            self.assertIn("| Baseline | Raw | Unique tasks | Duplicate | Unidentified |", report)
            self.assertIn("Detector/harness consistency audit", report)
            self.assertIn("detector_harness_disagreements.csv", report)
            self.assertIn("Finish-reason and length diagnostics", report)
            snippet = (output / "paper_integration_snippet.tex").read_text(encoding="utf-8")
            self.assertIn("do not support a cross-baseline effectiveness claim", snippet)
            self.assertIn("B3 0/120", snippet)
            self.assertNotIn("All figures in this paragraph\nproperty", snippet)

    def test_rendered_report_and_snippet_pool_multiple_campaign_shards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = []
            for seed in (7, 8):
                source = root / f"seed{seed}" / "events.checkpoint.jsonl"
                source.parent.mkdir()
                source.write_text(
                    json.dumps(record(
                        "import torch\nassert torch.add(1, 2) == 3",
                        baseline="B1", task_id=f"task-{seed}", generation_seed=seed,
                    )) + "\n",
                    encoding="utf-8",
                )
                inputs.append(source)

            output = root / "out"
            manifest = analyze(inputs, output, expected_per_baseline=1, expected_per_group=1)
            self.assertEqual(manifest["campaign_combined"]["shard_count"], 2)
            self.assertEqual(manifest["rendered_campaign_view"], "campaign_combined")

            report = (output / "validation_report.md").read_text(encoding="utf-8")
            self.assertIn("pool 2 immutable seed shards (2 events)", report)
            self.assertIn("| B1 | 2 | 2 | 0 | 0 | 2 | 0 |", report)
            self.assertEqual(report.count("| B1 | 2 | 2 | 0 | 0 | 2 | 0 |"), 1)

            snippet = (output / "paper_integration_snippet.tex").read_text(encoding="utf-8")
            self.assertIn("containing 2 records", snippet)
            self.assertIn("B1 2/2", snippet)

    def test_incremental_refresh_skips_unchanged_and_tracks_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "checkpoint.jsonl"
            first = record("import torch\nassert torch.add(1, 2) == 3")
            source.write_text(json.dumps(first) + "\n", encoding="utf-8")
            output = root / "out"
            updated, detail = refresh_once(source, None, output)
            self.assertTrue(updated)
            self.assertEqual(detail["classified_records"], 1)
            updated, _ = refresh_once(source, None, output)
            self.assertFalse(updated)
            manifest_path = output / "analysis_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["categories"] = []  # simulate stale logic with unchanged inputs
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            updated, _ = refresh_once(source, None, output)
            self.assertTrue(updated)
            with source.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**first, "generation_seed": 8}) + "\n")
            updated, detail = refresh_once(source, None, output)
            self.assertTrue(updated)
            self.assertEqual(detail["classified_records"], 2)
            history = (output / "checkpoint_history.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(history), 2)

    def test_review_sample_is_deterministic_and_agreement_is_computable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "checkpoint.jsonl"
            values = [
                record("import torch\nassert torch.add(1, 2) == 3", generation_seed=seed)
                for seed in range(4)
            ]
            source.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")
            review_dir = root / "review"
            first = build_sample(source, review_dir, sample_size=3)
            first_csv = (review_dir / "review_sample.csv").read_text(encoding="utf-8")
            second = build_sample(source, review_dir, sample_size=3)
            self.assertEqual(first["selected_records"], second["selected_records"])
            self.assertEqual(first_csv, (review_dir / "review_sample.csv").read_text(encoding="utf-8"))
            self.assertIn("sample_auto_label_counts", first)
            self.assertEqual(first["review_tool_sha256"], REVIEW_TOOL_SHA256)
            self.assertEqual(first["analyzer_sha256"], LOADED_ANALYZER_SHA256)
            self.assertEqual(
                sum(first["population_auto_label_counts"]["syntax_error"].values()),
                len(values),
            )
            self.assertTrue(first["population_stratum_candidate_counts"])
            self.assertEqual(
                sum(first["sample_auto_label_counts"]["syntax_error"].values()),
                first["selected_records"],
            )

            with (review_dir / "review_sample.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(all(row["review_tool_sha256"] == REVIEW_TOOL_SHA256 for row in rows))
            self.assertTrue(all(row["analyzer_sha256"] == LOADED_ANALYZER_SHA256 for row in rows))
            for row in rows:
                for category in CATEGORIES:
                    row[f"review_{category}"] = row[f"auto_{category}"]
            fields = list(rows[0])
            reviewer_a, reviewer_b = root / "a.csv", root / "b.csv"
            for target, reviewer_id in ((reviewer_a, "reviewer-a"), (reviewer_b, "reviewer-b")):
                reviewer_rows = [{**row, "reviewer_id": reviewer_id} for row in rows]
                with target.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(reviewer_rows)
            result = compute_agreement(reviewer_a, reviewer_b, root / "agreement")
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["review_tool_sha256"], REVIEW_TOOL_SHA256)
            self.assertEqual(result["sample_analyzer_sha256"], LOADED_ANALYZER_SHA256)
            self.assertTrue(result["sample_tools_match_current"])
            self.assertTrue(result["identities_distinct"])
            self.assertTrue(all(row["raw_agreement"] == 1.0 for row in result["categories"]))
            self.assertTrue(all(
                row["auto_vs_consensus_agreement"] == 1.0 for row in result["categories"]
            ))

            blank = root / "blank.csv"
            blank.write_text(first_csv, encoding="utf-8")
            pending = compute_agreement(blank, blank, root / "pending")
            self.assertEqual(pending["status"], "pending_unfilled_reviews")

            partial_rows = [dict(row) for row in rows]
            for row in partial_rows:
                for category in CATEGORIES:
                    row[f"review_{category}"] = ""
            partial_rows[0]["review_syntax_error"] = "true"
            partial_a, partial_b = root / "partial-a.csv", root / "partial-b.csv"
            for target, reviewer_id in ((partial_a, "reviewer-a"), (partial_b, "reviewer-b")):
                material = [{**row, "reviewer_id": reviewer_id} for row in partial_rows]
                with target.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(material)
            partial = compute_agreement(partial_a, partial_b, root / "partial")
            self.assertEqual(partial["status"], "pending_partial_reviews")

            changed = [{**row, "reviewer_id": "reviewer-b"} for row in rows]
            changed[0]["api"] = "torch.subtract"
            with reviewer_b.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(changed)
            with self.assertRaisesRegex(ValueError, "review metadata differs"):
                compute_agreement(reviewer_a, reviewer_b, root / "tampered")

            changed = [{**row, "reviewer_id": "reviewer-b"} for row in rows]
            changed[0]["extracted_code"] += "\n# accidental reviewer edit"
            with reviewer_b.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(changed)
            with self.assertRaisesRegex(ValueError, "extracted_code"):
                compute_agreement(reviewer_a, reviewer_b, root / "tampered-code")


if __name__ == "__main__":
    unittest.main()
