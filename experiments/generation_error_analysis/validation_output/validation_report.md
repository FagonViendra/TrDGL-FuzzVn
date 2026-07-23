# Validation-only generation failure report

> This is a partial-checkpoint validation artifact, not a completed benchmark result.

## Input snapshots

| Source | Role | Records | SHA-256 |
|---|---:|---:|---|
| events.checkpoint | campaign_checkpoint | 480 | `55e61acab475d370f6261be2041fdbb74ef5f06bd8197044df587c60a4f4af09` |
| colab_smoke_4baseline_events_latest | smoke_validation | 4 | `f2d8b57c63c5f52556680ed21a2e647dd0984bf923780047cf5151955bbb2f62` |

## Ledger integrity

| Source | Missing task ID | Duplicate task/baseline | Unexpected baseline | Run signatures | Seeds |
|---|---:|---:|---:|---:|---:|
| events.checkpoint | 0 | 0 | 0 | 1 | 1 |
| colab_smoke_4baseline_events_latest | 0 | 0 | 0 | 1 | 1 |

## Campaign coverage

Coverage uses unique non-empty task IDs; raw, duplicate, and unidentified JSONL rows are shown separately.

| Baseline | Raw | Unique tasks | Duplicate | Unidentified | Expected | Missing |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 120 | 120 | 0 | 0 | 120 | 0 |
| B1 | 120 | 120 | 0 | 0 | 120 | 0 |
| B2 | 120 | 120 | 0 | 0 | 120 | 0 |
| B3 | 120 | 120 | 0 | 0 | 120 | 0 |

Baseline-by-API-group estimates, Wilson intervals, and row-specific coverage are in `group_error_rates.csv`; the LaTeX rendering is `validation_group_rates.tex`.

## Within-baseline truncation associations

Cells are positive/eligible (rate [Wilson 95% CI]) in percent. Risk difference (RD) is truncated minus non-truncated. These are descriptive associations, not causal effects.

| Baseline | Outcome | Coverage | Truncated | Not truncated | RD (pp) | Unknown |
|---|---|---:|---:|---:|---:|---:|
| B0 | `parseable` | 120/120 | -- | 120/120 (100.0 [96.9, 100.0]) | -- | 0 |
| B0 | `oracle_bearing` | 120/120 | -- | 0/120 (0.0 [0.0, 3.1]) | -- | 0 |
| B0 | `standalone_oracle_reachable` | 120/120 | -- | 0/120 (0.0 [0.0, 3.1]) | -- | 0 |
| B1 | `parseable` | 120/120 | -- | 120/120 (100.0 [96.9, 100.0]) | -- | 0 |
| B1 | `oracle_bearing` | 120/120 | -- | 5/120 (4.2 [1.8, 9.4]) | -- | 0 |
| B1 | `standalone_oracle_reachable` | 120/120 | -- | 5/120 (4.2 [1.8, 9.4]) | -- | 0 |
| B2 | `parseable` | 120/120 | 55/110 (50.0 [40.8, 59.2]) | 10/10 (100.0 [72.2, 100.0]) | -50.0 | 0 |
| B2 | `oracle_bearing` | 120/120 | 52/55 (94.5 [85.1, 98.1]) | 10/10 (100.0 [72.2, 100.0]) | -5.5 | 55 |
| B2 | `standalone_oracle_reachable` | 120/120 | 0/55 (0.0 [0.0, 6.5]) | 10/10 (100.0 [72.2, 100.0]) | -100.0 | 55 |
| B3 | `parseable` | 120/120 | 2/120 (1.7 [0.5, 5.9]) | -- | -- | 0 |
| B3 | `oracle_bearing` | 120/120 | 0/2 (0.0 [0.0, 65.8]) | -- | -- | 118 |
| B3 | `standalone_oracle_reachable` | 120/120 | 0/2 (0.0 [0.0, 65.8]) | -- | -- | 118 |

## Finish-reason and length diagnostics

Token and generation-time fields are descriptive harness telemetry; missing values are not imputed.

| Baseline | Finish reason | N | Token known | Token min / median / p95 / max | Mean generation seconds |
|---|---|---:|---:|---:|---:|
| B0 | `__ALL__` | 120 | 0 | -- / -- / -- / -- | 0.00 |
| B0 | `template` | 120 | 0 | -- / -- / -- / -- | 0.00 |
| B1 | `__ALL__` | 120 | 120 | 43 / 193 / 366 / 509 | 5.70 |
| B1 | `stop` | 120 | 120 | 43 / 193 / 366 / 509 | 5.70 |
| B2 | `__ALL__` | 120 | 120 | 476 / 600 / 600 / 600 | 18.32 |
| B2 | `length` | 110 | 110 | 599 / 600 / 600 / 600 | 18.52 |
| B2 | `stop` | 10 | 10 | 476 / 533 / 583 / 583 | 16.13 |
| B3 | `__ALL__` | 120 | 120 | 599 / 600 / 600 / 603 | 19.04 |
| B3 | `length` | 120 | 120 | 599 / 600 / 600 / 603 | 19.04 |

## Observed campaign failures and unknown evidence

Rates below divide by known evidence only. Unknown observations remain in the `U` column.

| Baseline | Failure mode | N | Present | U | Known-evidence rate |
|---|---|---:|---:|---:|---:|
| B0 | `missing_oracle` | 120 | 120 | 0 | 100.0% |
| B0 | `nondeterministic_failure` | 120 | 0 | 120 | -- |
| B1 | `wrong_or_missing_target_api` | 120 | 6 | 0 | 5.0% |
| B1 | `shape_or_dtype_error` | 120 | 7 | 0 | 5.8% |
| B1 | `index_or_bounds_error` | 120 | 2 | 0 | 1.7% |
| B1 | `undefined_name_error` | 120 | 1 | 0 | 0.8% |
| B1 | `argument_signature_error` | 120 | 3 | 0 | 2.5% |
| B1 | `runtime_error_other` | 120 | 3 | 0 | 2.5% |
| B1 | `assertion_failure` | 120 | 1 | 0 | 0.8% |
| B1 | `missing_oracle` | 120 | 115 | 0 | 95.8% |
| B1 | `broad_exception_swallowing` | 120 | 3 | 0 | 2.5% |
| B1 | `nondeterministic_failure` | 120 | 0 | 120 | -- |
| B2 | `syntax_error` | 120 | 55 | 0 | 45.8% |
| B2 | `wrong_or_missing_target_api` | 120 | 0 | 55 | 0.0% |
| B2 | `missing_import` | 120 | 0 | 55 | 0.0% |
| B2 | `shape_or_dtype_error` | 120 | 0 | 55 | 0.0% |
| B2 | `index_or_bounds_error` | 120 | 0 | 55 | 0.0% |
| B2 | `undefined_name_error` | 120 | 0 | 55 | 0.0% |
| B2 | `argument_signature_error` | 120 | 0 | 55 | 0.0% |
| B2 | `dependency_import_error` | 120 | 0 | 55 | 0.0% |
| B2 | `setup_or_environment_error` | 120 | 0 | 55 | 0.0% |
| B2 | `resource_exhaustion` | 120 | 0 | 55 | 0.0% |
| B2 | `runtime_error_other` | 120 | 0 | 55 | 0.0% |
| B2 | `assertion_failure` | 120 | 1 | 55 | 1.5% |
| B2 | `missing_oracle` | 120 | 3 | 55 | 4.6% |
| B2 | `oracle_not_executed` | 120 | 52 | 55 | 80.0% |
| B2 | `fake_assertion` | 120 | 2 | 55 | 3.1% |
| B2 | `broad_exception_swallowing` | 120 | 0 | 55 | 0.0% |
| B2 | `target_not_executed` | 120 | 55 | 55 | 84.6% |
| B2 | `truncated_generation` | 120 | 110 | 0 | 91.7% |
| B2 | `nondeterministic_failure` | 120 | 0 | 120 | -- |
| B3 | `syntax_error` | 120 | 118 | 0 | 98.3% |
| B3 | `wrong_or_missing_target_api` | 120 | 0 | 118 | 0.0% |
| B3 | `missing_import` | 120 | 0 | 118 | 0.0% |
| B3 | `shape_or_dtype_error` | 120 | 0 | 118 | 0.0% |
| B3 | `index_or_bounds_error` | 120 | 0 | 118 | 0.0% |
| B3 | `undefined_name_error` | 120 | 1 | 118 | 50.0% |
| B3 | `argument_signature_error` | 120 | 0 | 118 | 0.0% |
| B3 | `dependency_import_error` | 120 | 0 | 118 | 0.0% |
| B3 | `setup_or_environment_error` | 120 | 0 | 118 | 0.0% |
| B3 | `resource_exhaustion` | 120 | 0 | 118 | 0.0% |
| B3 | `runtime_error_other` | 120 | 0 | 118 | 0.0% |
| B3 | `assertion_failure` | 120 | 0 | 118 | 0.0% |
| B3 | `missing_oracle` | 120 | 2 | 118 | 100.0% |
| B3 | `oracle_not_executed` | 120 | 0 | 118 | 0.0% |
| B3 | `fake_assertion` | 120 | 0 | 118 | 0.0% |
| B3 | `broad_exception_swallowing` | 120 | 0 | 118 | 0.0% |
| B3 | `target_not_executed` | 120 | 1 | 118 | 50.0% |
| B3 | `truncated_generation` | 120 | 120 | 0 | 100.0% |
| B3 | `nondeterministic_failure` | 120 | 0 | 120 | -- |

## Detector/harness consistency audit

Only eligible, known labels enter the agreement denominator. This is a diagnostic comparison, not accuracy.

| Baseline | Category | Comparable | Agree | Disagree | H+ / A- | H- / A+ | Harness U | Analyzer U |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B1 | `wrong_or_missing_target_api` | 120 | 85 | 35 | 35 | 0 | 0 | 0 |
| B2 | `wrong_or_missing_target_api` | 65 | 49 | 16 | 16 | 0 | 55 | 0 |
| B3 | `wrong_or_missing_target_api` | 2 | 0 | 2 | 2 | 0 | 118 | 0 |

All audit rows, including zero-disagreement signals, are in `detector_harness_comparison.csv`. Row-level pointers and canonicalized call evidence are in `detector_harness_disagreements.csv`. Disagreements require manual review; for example, the AST detector can resolve `F.*` aliases that a harness string matcher misses.

## Interpretation guardrails

- Smoke-validation records are reported separately and are not pooled into campaign rates.
- A rate of `--` means there is no known denominator; it does not mean 0%.
- Missing baselines/groups must be completed before any cross-baseline claim.
- `missing_oracle` can be a baseline design property (not a PyTorch defect); interpret it as generated-test quality.
- `target_not_executed` means the API call occurs only inside a function that the standalone script never invokes.
