# Generation-error analysis (validation only)

This directory implements the program-generation failure analysis requested
for Section 4. It consumes benchmark JSONL evidence and **does not execute any
generated program**. Static findings come from `ast`; runtime findings come
only from the subprocess fields recorded by the common benchmark harness.
Exact decision rules and validity boundaries are documented in [METHOD.md](METHOD.md).

## Reproduce the current snapshot

Run from the repository root:

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/analyze_generation_errors.py `
  --input tmp/seed3407_progress.jsonl `
  --input tmp/colab_smoke_4baseline/events_latest.jsonl `
  --output-dir TrDGL-FuzzVn_paper/experiments/generation_error_analysis/validation_output
```

## Two-seed diagnostic checkpoint

The immutable 960-event analysis for complete shards 3407 and 7711 is kept
separately from the stable one-seed snapshot:

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/analyze_generation_errors.py `
  --input TrDGL-FuzzVn_paper/experiments/benchmark_120/checkpoints/seed3407_480/events.checkpoint.jsonl `
  --input TrDGL-FuzzVn_paper/experiments/benchmark_120/checkpoints/seed7711_480/events.checkpoint.jsonl `
  --output-dir TrDGL-FuzzVn_paper/experiments/generation_error_analysis/two_seed_checkpoint
```

`two_seed_checkpoint/validation_report.md` renders the pooled campaign view
(240 records per baseline), while the per-source JSON/CSV outputs retain both
input hashes and shard-level rows. This is a two-of-five-seed diagnostic
checkpoint, not a completed benchmark result.

The corresponding deterministic 24-record review sheet is regenerated with:

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/review_validation.py sample `
  --input TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/events.combined.jsonl `
  --output-dir TrDGL-FuzzVn_paper/experiments/generation_error_analysis/two_seed_review `
  --sample-size 24
```

Its status remains `awaiting_two_independent_reviewers`; generating a sample is
not evidence that review or agreement has occurred.

Then run the standard-library test suite:

```powershell
python -m unittest discover -s TrDGL-FuzzVn_paper/experiments/generation_error_analysis -p "test_*.py" -v
```

For later seed-3407 checkpoints, the zero-argument incremental command reruns
only when an input hash changed and appends a compact history entry:

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/refresh_checkpoint.py
```

To keep refreshing while Colab appends checkpoint records (stop with Ctrl+C):

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/refresh_checkpoint.py --watch --poll-seconds 20
```

This watcher is CPU-only and never starts, reconnects, or reserves a Colab
runtime. A lock prevents two refreshers from writing the same output directory.
Each refresh is rendered in a temporary staging directory; complete files are
atomically replaced and `analysis_manifest.json` is published last as the
commit marker. An interrupted refresh is therefore detected on the next poll
instead of being mistaken for a current, complete artifact set.

## Manual detector validation

Build a deterministic, stratified 24-record review sheet from the campaign.
Multi-label records participate in every positive-category stratum; known
analyzer/harness disagreements receive additional strata. Records are
de-duplicated at selection, giving rare secondary detectors and consistency
cases a chance to enter the sheet:

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/review_validation.py sample `
  --input tmp/seed3407_progress.jsonl `
  --output-dir TrDGL-FuzzVn_paper/experiments/generation_error_analysis/review_validation
```

Two reviewers must independently copy and fill the `review_*` columns with
`true`, `false`, or `unknown`. Agreement is computed only after both files are
filled; blank cells remain pending:

```powershell
python TrDGL-FuzzVn_paper/experiments/generation_error_analysis/review_validation.py agreement `
  --reviewer-a reviewer_a.csv --reviewer-b reviewer_b.csv `
  --output-dir reviewer_agreement
```

This creates review infrastructure only. It does not claim that independent
review or agreement has occurred. Agreement is marked `complete` only when the
two files contain the same record set, every category has a paired label, and
each file consistently names a distinct non-empty reviewer ID. Immutable sample
metadata must match across files; edited task/API/code/diagnostic/evidence or
automatic-label fields are rejected instead of being compared.
For labels on which both reviewers agree, the agreement output also reports
automatic-label agreement and a tri-state confusion table against reviewer
consensus. This is a validation diagnostic, not an adjudicated gold-standard
accuracy estimate.
The sample manifest also reports population candidate counts per selection
stratum and population-versus-sample tri-state label counts, so coverage and
selection skew remain auditable.

## Evidence semantics

Every category is tri-state:

- `true`: the failure is positively identified;
- `false`: available evidence rules it out;
- blank/`null`: unknown, usually because parsing or subprocess execution did
  not occur.

Rates use `n_known = n_true + n_false`; `n_unknown` is always printed beside
them. Failed parsing therefore does not turn `missing_oracle=false`,
`wrong_api=false`, or `missing_import=false` by accident.

Coverage counts unique non-empty `task_id` values, not raw JSONL rows. Raw,
duplicate, and unidentified row counts remain beside the coverage denominator,
so a repeated append cannot make an incomplete slice appear complete. The
input-integrity audit is descriptive and never removes records. It flags
missing task IDs, repeated `(baseline, task_id)` identities, unexpected
baseline labels, and the number of distinct run signatures and seeds. Thus a
duplicate append cannot pass unnoticed merely because a raw row count reached
the nominal target.

The campaign checkpoint and smoke-validation ledger remain separate sources.
Smoke rows verify all four runner paths but are never pooled into the campaign
failure rates. `coverage_summary.*` materializes B0--B3 even when a baseline
has zero records, preventing an incomplete checkpoint from looking complete.

## Categories

The analyzer reports syntax, wrong/missing target API, missing imports,
shape/dtype, index/bounds, undefined-name, argument-signature,
dependency-import, assertion and other runtime errors, setup/environment
failures, resource exhaustion, timeout,
missing oracle, oracle present only on an unreachable standalone path, fake
assertion, broad exception
swallowing, target code placed only in an uninvoked function, and
length-truncated generation. Each event retains a compact evidence string for
every decision. Recognized oracle syntax includes Python `assert`, explicit
`AssertionError` raises, `torch._assert`, and common aliased PyTorch, NumPy,
and unittest assertion helpers.

## Outputs

- `event_classification.csv` / `.jsonl`: audit ledger at generation level,
  including subprocess exit code and a bounded diagnostic excerpt for failed
  executions;
- `failure_summary.csv` / `.json`: source, baseline, baseline-by-group, seed,
  seed-by-baseline, and seed-by-baseline-by-group denominators;
- `coverage_summary.csv` / `.json`: explicit completeness audit;
- `group_error_rates.csv` / `.json` and `validation_group_rates.tex`:
  baseline-by-API-group tri-state rates, Wilson 95% intervals, and coverage;
- `campaign_combined_failure_summary.*`, `campaign_combined_coverage.*`, and
  `campaign_combined_group_error_rates.*`: cross-shard view whose expected
  denominator scales by distinct generation seed; each original input remains
  separately hashed in the manifest;
- `truncation_associations.csv` / `.json` and
  `validation_truncation_associations.tex`: within-baseline descriptive
  association of truncation with parseability, oracle bearing, and standalone
  oracle reachability, never a causal
  or partial-run cross-model claim;
- `length_diagnostics.csv` / `.json`: finish-reason counts plus available token
  count, generation/subprocess time, and paired token-throughput distributions,
  including explicit zero-record baselines;
- `seed_telemetry.csv` / `.json`: identity coverage and non-imputed token,
  generation-time, subprocess-time, and throughput summaries for each
  `(source, generation seed, baseline)` slice;
- `input_integrity.json`: duplicate-identity and ledger-field audit;
- `detector_harness_comparison.csv` / `.json`: agreement audit for eligible
  analyzer/harness labels; this is diagnostic agreement, not detector accuracy;
- `detector_harness_disagreements.csv` / `.json`: row-level disagreement
  pointers with source hash, task/API identity, both labels, and analyzer
  evidence (including resolved API aliases);
- `failure_case_catalog.csv` / `.json`: deterministic first positive case per
  source, baseline, and category, traceable by source hash, JSONL line, task ID,
  raw-output hash, exit code, and a bounded single-line stderr excerpt;
- `failure_case_catalog.md`: compact human-readable rendering of the same audit
  pointers for Section 4.7 case selection;
- `validation_tables.tex`: clearly labeled validation-only LaTeX tables;
- `validation_report.md`: concise coverage and observed-failure interpretation;
- `paper_integration_snippet.tex`: validation-only prose for Sections 4.3/4.7
  that explicitly forbids a partial-run cross-baseline claim;
- `analysis_manifest.json`: source hashes, record counts, semantics, and tool
  version.

These outputs are safe to inspect during a partial run. They must not be
described as final experimental results until campaign coverage is complete.
