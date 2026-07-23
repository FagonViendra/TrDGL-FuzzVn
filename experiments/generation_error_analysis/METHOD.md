# Classification method and validity boundaries

The unit of analysis is one raw generation record emitted by the common
benchmark harness. A category is a **failure-present indicator**, not a funnel
stage. Multiple indicators can be true for the same generation; counts are
therefore not mutually exclusive and must not be summed.

## Decision rules

| Category | Positive evidence | Unknown when |
|---|---|---|
| `syntax_error` | `ast.parse` raises `SyntaxError` | extracted code is absent |
| `wrong_or_missing_target_api` | parsed AST and neither harness nor AST recognizes the requested API call | code cannot be parsed or target API metadata is absent |
| `missing_import` | a known module alias (`torch`, `np`, `numpy`, `F`) is loaded but unbound, or subprocess stderr records a corresponding `NameError` | code cannot be parsed |
| `shape_or_dtype_error` | nonzero subprocess exit plus a shape/dtype diagnostic | subprocess has no exit code |
| `index_or_bounds_error` | nonzero subprocess exit plus an index out-of-range/bounds diagnostic | subprocess has no exit code |
| `undefined_name_error` | nonzero subprocess exit plus `NameError` for an undefined name | subprocess has no exit code |
| `argument_signature_error` | nonzero exit plus missing/duplicate/unexpected argument or wrong argument-instance diagnostic | subprocess has no exit code |
| `dependency_import_error` | nonzero exit plus `ModuleNotFoundError`/`ImportError` | subprocess has no exit code |
| `setup_or_environment_error` | nonzero exit plus missing driver/CUDA/shared-library diagnostic | subprocess has no exit code |
| `resource_exhaustion` | nonzero exit plus host/CUDA allocation failure | subprocess has no exit code |
| `runtime_error_other` | nonzero subprocess exit not assigned to another runtime category or timeout | subprocess has no exit code |
| `assertion_failure` | nonzero subprocess exit with `AssertionError` | subprocess has no exit code |
| `timeout` | harness timeout flag is true | timeout flag is absent/ambiguous |
| `missing_oracle` | parsed program has no harness- or AST-recognized assertion/check | code cannot be parsed |
| `oracle_not_executed` | a recognized oracle occurs only in a top-level function unreachable from standalone module execution | code cannot be parsed or static reachability is unresolved |
| `fake_assertion` | literal-only always-pass/fail assert, self-comparison, self-`assert_close`, or harness fake-assertion flag | code cannot be parsed |
| `broad_exception_swallowing` | bare/`Exception`/`BaseException` handler has no re-raise | code cannot be parsed |
| `target_not_executed` | requested API occurs only inside a function never called from module execution scope | code cannot be parsed or target API is absent |
| `truncated_generation` | `finish_reason=length` | finish reason is absent |
| `nondeterministic_failure` | recorded `reproducible=false` or at least two unequal replay outcomes | fewer than two replay outcomes are available |

## Denominators

Each summary row exposes `n_total`, `n_true`, `n_false`, `n_unknown`, and
`n_known`. The reported rate is `n_true / n_known`; the companion lower bound
is `n_true / n_total`. Baseline and baseline-by-API-group rows are emitted
independently for each input source. This prevents the four-record smoke test
from silently inflating the campaign checkpoint.

Baseline-by-API-group rows join each tri-state failure rate to the corresponding
observed/expected/missing coverage. Observed coverage is the number of unique,
non-empty `task_id` values. Raw, duplicate, and unidentified row counts are
reported separately; unidentified rows do not prove task coverage. Rates use
known evidence only. Two-sided
Wilson 95% intervals are emitted only when `n_known > 0`; an empty denominator
is represented as missing, never as a zero-width interval or a 0% estimate.

The combined-campaign view pools only `campaign_checkpoint` inputs. Its
expected baseline and API-group denominators are the single-shard expectations
multiplied by the number of distinct non-empty generation seeds. Task IDs still
control observed coverage, so repeated inputs for the same seed become
duplicate rows rather than silently increasing either coverage or the expected
denominator. Per-source rows and hashes remain available for shard-level audit.
If legacy campaign records omit a generation seed, every affected source is
counted as an additional conservative shard and listed in
`unknown_seed_sources`; it cannot disappear from the expected denominator just
because another source reports a valid seed.

When multiple campaign shards are supplied, the human-readable validation
report, paper snippet, and LaTeX renderings use this explicit synthetic
`campaign_combined` view. Per-source JSON/CSV outputs and source hashes remain
unchanged for shard-level audit; the renderer must not print several unlabeled
single-shard tables as though they were one campaign table.

The truncation analysis is stratified within source and baseline. For each
baseline it describes parseability, oracle-bearing, and standalone-reachable
oracle rates among records with
`finish_reason=length` and among records with other known finish reasons,
including Wilson intervals and the descriptive risk difference (truncated
minus non-truncated). Unknown truncation/outcome evidence is counted and
excluded from the corresponding denominator. This is an association audit,
not a causal estimate; incomplete coverage precludes cross-model conclusions.

Finish-reason diagnostics preserve harness token count, generation duration,
and subprocess duration when present. Median and p95 use the deterministic
nearest-rank empirical quantile. Aggregate token throughput is the sum of
known token counts divided by the sum of their paired positive generation
durations; per-record median and p95 throughput use only those same eligible
pairs. Missing token counts or durations (for example, template baselines) are
reported through explicit known-pair denominators rather than imputed.
`seed_telemetry.*` repeats these descriptive fields for each source, generation
seed, and baseline, while `failure_summary.*` includes seed-stratified
tri-state denominators.

## Validity boundaries

- Static checks are deliberately conservative and do not claim semantic
  equivalence between arbitrary expressions.
- Missing-import analysis combines recorded runtime `NameError` evidence with
  scope-aware checks for conventional module aliases. Imports in an unrelated
  function or a literal-dead branch do not incorrectly bind a module-level
  reference; module imports remain visible to top-level helper functions.
- Oracle bearing and oracle execution are distinct: `missing_oracle` recognizes
  Python `assert`, explicit `AssertionError` raises, `torch._assert`, and common
  PyTorch/NumPy/unittest assertion helpers (including import aliases), while
  `oracle_not_executed` uses conservative top-level call-graph reachability for
  the standalone harness.
- Fake-oracle detection covers literal-only assertions and `_assert`/unittest
  helpers, plus self-comparison across aliased PyTorch, NumPy, and unittest
  comparison helpers. It does not attempt to prove arbitrary expressions
  vacuous.
- Shape/dtype labels require recorded runtime diagnostics; a script that never
  invokes its generated test cannot provide negative evidence about the API
  behavior itself. `target_not_executed` exposes that condition separately.
- Runtime audit excerpts prefer the last explicit exception line and are
  bounded to 240 characters. If the harness has already truncated stderr so
  that no exception line remains, the analyzer retains bounded start/end text
  and leaves the failure in `runtime_error_other`; it does not infer a cause.
- A broad handler is labeled only when it catches every ordinary exception and
  does not re-raise. Catching a specific exception is not labeled.
- `target_not_executed` assumes the artifact is executed as a standalone
  subprocess, matching the benchmark harness. It would not apply unchanged to
  pytest collection. Static reachability follows direct and directly aliased
  top-level helper chains and prunes branches proven dead by literal Boolean
  tests. Unknown conditions retain both branches; dynamic dispatch and
  class-method invocation remain unresolved rather than guessed.
- These categories describe generation quality, not confirmed PyTorch bugs.

## Checkpoint and publication integrity

The analyzer reads and hashes each JSONL input from the same immutable byte
snapshot. A partial trailing JSON object is rejected rather than silently
dropped; watch mode retries it on the next poll. Refreshes are produced in a
staging directory, every expected file is checked before publication, and the
manifest is atomically replaced last. The manifest source hashes and analyzer
hash are the freshness boundary: a checkpoint append or detector-code change
forces regeneration. The output lock carries a unique owner token so a stale
owner cannot remove a successor's lock during cleanup.

An additional non-destructive integrity audit reports missing task IDs,
duplicate `(baseline, task_id)` identities, unexpected baseline names, and the
number of run signatures and generation seeds per input source. These checks
do not deduplicate the analysis; they make accidental over-counting visible.

The detector/harness comparison is an internal consistency audit, not a
validation gold standard. Target, oracle, and fake-assertion harness fields are
compared only when the harness records `parseable=true`; false defaults after a
parse failure remain unknown. An AST/harness disagreement can be an intentional
static correction and must be manually reviewed before changing a detector.
The audit reports both disagreement directions separately because, for a
failure-present label, harness-true/analyzer-false has a different meaning from
harness-false/analyzer-true.
Every disagreement is also materialized as a row-level audit pointer. For
target-call disagreements, evidence records the source spelling and canonical
call name (for example, `F.conv2d -> torch.nn.functional.conv2d`) so alias
resolution can be reviewed without treating either implementation as truth.
For exact-target failures, evidence also records conservative near misses such
as the same terminal name on a tensor receiver, an in-place suffix variant, or
a constructor missing `_tensor`; near misses never override the failure label.

For qualitative inspection, the case catalog selects the earliest positive
record for each `(source, baseline, category)` tuple. Selection is deterministic
and retains the source SHA-256, JSONL line number, task ID, API, seed, and raw
output hash. It is an audit pointer, not an additional observation or a
cross-baseline comparison.

The manual-review sheet uses deterministic round-robin sampling across every
`(baseline, positive automatic label)` and known analyzer/harness-disagreement
stratum. A multi-label record enters all applicable candidate strata but is
selected at most once; records without a positive detector or disagreement
enter a `no_detected_failure` fallback stratum. This improves detector coverage
without pretending that the resulting sample is a random estimate of campaign
prevalence.
Its manifest records both population candidate counts for each sampling
stratum and population/sample tri-state label counts for every detector. These
counts expose selection skew and absent strata; they do not turn the targeted
qualitative sample into a probability sample.

Manual detector validation requires complete tri-state labels from two
distinct, consistently identified reviewers over the identical review-key
set. Agreement tooling rejects changed immutable metadata and distinguishes
unfilled, partially filled, identity-unverified, and complete reviews; it does
not convert partial annotation into a completed validation claim.
Immutable review metadata includes generated code, stderr, automatic evidence,
and every automatic label, preventing reviewer-sheet edits from silently
changing the evaluated item.
Both sample and agreement manifests pin the analyzer and review-tool SHA-256,
so a later code change cannot masquerade as the original annotation protocol.
Every reviewer row carries the same pins. Agreement rejects missing or
internally inconsistent pins and reports whether the sampled tool versions
match the versions currently computing agreement; an older immutable sample
therefore remains analyzable without being mislabeled as current.
Cohen's kappa is reported as undefined when both reviewers have constant
marginals (zero denominator); raw agreement remains available in that case.
Automatic labels are compared only with labels on which the two reviewers
agree. The resulting auto-versus-consensus agreement and confusion counts are
diagnostic; unresolved reviewer disagreement is excluded rather than silently
adjudicated.
