# Validation-only generation failure report

> This is a partial-checkpoint validation artifact, not a completed benchmark result.

## Input snapshots

| Source | Role | Records | SHA-256 |
|---|---:|---:|---|
| events.checkpoint | campaign_checkpoint | 480 | `55e61acab475d370f6261be2041fdbb74ef5f06bd8197044df587c60a4f4af09` |
| events.checkpoint_2 | campaign_checkpoint | 480 | `8a27a2280f550887be0cf031f900ad1aec16a3441719c17683185c027315d6bc` |

## Checkpoint scope

The rendered campaign tables pool 2 immutable seed shards (960 events). Their within-checkpoint denominator is 240 records per baseline and 24 per API group. The planned design has five seed shards, so this remains a diagnostic checkpoint rather than a final campaign result.

## Ledger integrity

| Source | Missing task ID | Duplicate task/baseline | Unexpected baseline | Run signatures | Seeds |
|---|---:|---:|---:|---:|---:|
| events.checkpoint | 0 | 0 | 0 | 1 | 1 |
| events.checkpoint_2 | 0 | 0 | 0 | 1 | 1 |

## Campaign coverage

Coverage uses unique non-empty task IDs; raw, duplicate, and unidentified JSONL rows are shown separately.

| Baseline | Raw | Unique tasks | Duplicate | Unidentified | Expected | Missing |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 240 | 240 | 0 | 0 | 240 | 0 |
| B1 | 240 | 240 | 0 | 0 | 240 | 0 |
| B2 | 240 | 240 | 0 | 0 | 240 | 0 |
| B3 | 240 | 240 | 0 | 0 | 240 | 0 |

Baseline-by-API-group estimates, Wilson intervals, and row-specific coverage are in `campaign_combined_group_error_rates.csv`; the LaTeX rendering is `validation_group_rates.tex`.

## Within-baseline truncation associations

Cells are positive/eligible (rate [Wilson 95% CI]) in percent. Risk difference (RD) is truncated minus non-truncated. These are descriptive associations, not causal effects.

| Baseline | Outcome | Coverage | Truncated | Not truncated | RD (pp) | Unknown |
|---|---|---:|---:|---:|---:|---:|
| B0 | `parseable` | 240/240 | -- | 240/240 (100.0 [98.4, 100.0]) | -- | 0 |
| B0 | `oracle_bearing` | 240/240 | -- | 0/240 (0.0 [0.0, 1.6]) | -- | 0 |
| B0 | `standalone_oracle_reachable` | 240/240 | -- | 0/240 (0.0 [0.0, 1.6]) | -- | 0 |
| B1 | `parseable` | 240/240 | -- | 240/240 (100.0 [98.4, 100.0]) | -- | 0 |
| B1 | `oracle_bearing` | 240/240 | -- | 9/240 (3.8 [2.0, 7.0]) | -- | 0 |
| B1 | `standalone_oracle_reachable` | 240/240 | -- | 9/240 (3.8 [2.0, 7.0]) | -- | 0 |
| B2 | `parseable` | 240/240 | 119/219 (54.3 [47.7, 60.8]) | 21/21 (100.0 [84.5, 100.0]) | -45.7 | 0 |
| B2 | `oracle_bearing` | 240/240 | 113/119 (95.0 [89.4, 97.7]) | 21/21 (100.0 [84.5, 100.0]) | -5.0 | 100 |
| B2 | `standalone_oracle_reachable` | 240/240 | 0/119 (0.0 [0.0, 3.1]) | 21/21 (100.0 [84.5, 100.0]) | -100.0 | 100 |
| B3 | `parseable` | 240/240 | 5/240 (2.1 [0.9, 4.8]) | -- | -- | 0 |
| B3 | `oracle_bearing` | 240/240 | 0/5 (0.0 [0.0, 43.4]) | -- | -- | 235 |
| B3 | `standalone_oracle_reachable` | 240/240 | 0/5 (0.0 [0.0, 43.4]) | -- | -- | 235 |

## Finish-reason and length diagnostics

Token and generation-time fields are descriptive harness telemetry; missing values are not imputed.

| Baseline | Finish reason | N | Token known | Token min / median / p95 / max | Mean generation seconds |
|---|---|---:|---:|---:|---:|
| B0 | `__ALL__` | 240 | 0 | -- / -- / -- / -- | 0.00 |
| B0 | `template` | 240 | 0 | -- / -- / -- / -- | 0.00 |
| B1 | `__ALL__` | 240 | 240 | 43 / 191 / 366 / 509 | 5.62 |
| B1 | `stop` | 240 | 240 | 43 / 191 / 366 / 509 | 5.62 |
| B2 | `__ALL__` | 240 | 240 | 476 / 600 / 600 / 600 | 18.05 |
| B2 | `length` | 219 | 219 | 599 / 600 / 600 / 600 | 18.23 |
| B2 | `stop` | 21 | 21 | 476 / 564 / 597 / 598 | 16.16 |
| B3 | `__ALL__` | 240 | 240 | 599 / 600 / 600 / 603 | 18.57 |
| B3 | `length` | 240 | 240 | 599 / 600 / 600 / 603 | 18.57 |

## Observed campaign failures and unknown evidence

Rates below divide by known evidence only. Unknown observations remain in the `U` column.

| Baseline | Failure mode | N | Present | U | Known-evidence rate |
|---|---|---:|---:|---:|---:|
| B0 | `missing_oracle` | 240 | 240 | 0 | 100.0% |
| B0 | `nondeterministic_failure` | 240 | 0 | 240 | -- |
| B1 | `wrong_or_missing_target_api` | 240 | 12 | 0 | 5.0% |
| B1 | `shape_or_dtype_error` | 240 | 9 | 0 | 3.8% |
| B1 | `index_or_bounds_error` | 240 | 2 | 0 | 0.8% |
| B1 | `undefined_name_error` | 240 | 1 | 0 | 0.4% |
| B1 | `argument_signature_error` | 240 | 6 | 0 | 2.5% |
| B1 | `runtime_error_other` | 240 | 7 | 0 | 2.9% |
| B1 | `assertion_failure` | 240 | 1 | 0 | 0.4% |
| B1 | `missing_oracle` | 240 | 231 | 0 | 96.2% |
| B1 | `broad_exception_swallowing` | 240 | 5 | 0 | 2.1% |
| B1 | `nondeterministic_failure` | 240 | 0 | 240 | -- |
| B2 | `syntax_error` | 240 | 100 | 0 | 41.7% |
| B2 | `wrong_or_missing_target_api` | 240 | 1 | 100 | 0.7% |
| B2 | `missing_import` | 240 | 0 | 100 | 0.0% |
| B2 | `shape_or_dtype_error` | 240 | 0 | 100 | 0.0% |
| B2 | `index_or_bounds_error` | 240 | 0 | 100 | 0.0% |
| B2 | `undefined_name_error` | 240 | 1 | 100 | 0.7% |
| B2 | `argument_signature_error` | 240 | 0 | 100 | 0.0% |
| B2 | `dependency_import_error` | 240 | 0 | 100 | 0.0% |
| B2 | `setup_or_environment_error` | 240 | 0 | 100 | 0.0% |
| B2 | `resource_exhaustion` | 240 | 0 | 100 | 0.0% |
| B2 | `runtime_error_other` | 240 | 2 | 100 | 1.4% |
| B2 | `assertion_failure` | 240 | 3 | 100 | 2.1% |
| B2 | `missing_oracle` | 240 | 6 | 100 | 4.3% |
| B2 | `oracle_not_executed` | 240 | 113 | 100 | 80.7% |
| B2 | `fake_assertion` | 240 | 4 | 100 | 2.9% |
| B2 | `broad_exception_swallowing` | 240 | 1 | 100 | 0.7% |
| B2 | `target_not_executed` | 240 | 118 | 100 | 84.3% |
| B2 | `truncated_generation` | 240 | 219 | 0 | 91.2% |
| B2 | `nondeterministic_failure` | 240 | 0 | 240 | -- |
| B3 | `syntax_error` | 240 | 235 | 0 | 97.9% |
| B3 | `wrong_or_missing_target_api` | 240 | 0 | 235 | 0.0% |
| B3 | `missing_import` | 240 | 0 | 235 | 0.0% |
| B3 | `shape_or_dtype_error` | 240 | 0 | 235 | 0.0% |
| B3 | `index_or_bounds_error` | 240 | 0 | 235 | 0.0% |
| B3 | `undefined_name_error` | 240 | 1 | 235 | 20.0% |
| B3 | `argument_signature_error` | 240 | 0 | 235 | 0.0% |
| B3 | `dependency_import_error` | 240 | 0 | 235 | 0.0% |
| B3 | `setup_or_environment_error` | 240 | 0 | 235 | 0.0% |
| B3 | `resource_exhaustion` | 240 | 0 | 235 | 0.0% |
| B3 | `runtime_error_other` | 240 | 0 | 235 | 0.0% |
| B3 | `assertion_failure` | 240 | 0 | 235 | 0.0% |
| B3 | `missing_oracle` | 240 | 5 | 235 | 100.0% |
| B3 | `oracle_not_executed` | 240 | 0 | 235 | 0.0% |
| B3 | `fake_assertion` | 240 | 0 | 235 | 0.0% |
| B3 | `broad_exception_swallowing` | 240 | 0 | 235 | 0.0% |
| B3 | `target_not_executed` | 240 | 3 | 235 | 60.0% |
| B3 | `truncated_generation` | 240 | 240 | 0 | 100.0% |
| B3 | `nondeterministic_failure` | 240 | 0 | 240 | -- |

## Detector/harness consistency audit

Only eligible, known labels enter the agreement denominator. This is a diagnostic comparison, not accuracy.

| Baseline | Category | Comparable | Agree | Disagree | H+ / A- | H- / A+ | Harness U | Analyzer U |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B1 | `wrong_or_missing_target_api` | 240 | 170 | 70 | 70 | 0 | 0 | 0 |
| B2 | `wrong_or_missing_target_api` | 140 | 102 | 38 | 38 | 0 | 100 | 0 |
| B2 | `fake_assertion` | 140 | 139 | 1 | 0 | 1 | 100 | 0 |
| B3 | `wrong_or_missing_target_api` | 5 | 1 | 4 | 4 | 0 | 235 | 0 |

All audit rows, including zero-disagreement signals, are in `detector_harness_comparison.csv`. Row-level pointers and canonicalized call evidence are in `detector_harness_disagreements.csv`. Disagreements require manual review; for example, the AST detector can resolve `F.*` aliases that a harness string matcher misses.

## Interpretation guardrails

- No smoke-validation input is pooled into this checkpoint; campaign rates use only immutable seed shards.
- A rate of `--` means there is no known denominator; it does not mean 0%.
- The remaining planned seed shards must be completed before a final cross-baseline claim.
- `missing_oracle` can be a baseline design property (not a PyTorch defect); interpret it as generated-test quality.
- `target_not_executed` means the API call occurs only inside a function that the standalone script never invokes.
