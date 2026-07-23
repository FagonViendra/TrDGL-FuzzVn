# Unified Vn funnel and candidate ledger

This directory is the machine-readable implementation of the paper's promotion policy. It does not change the 120-API generator notebook. It consumes the notebook's append-only JSONL events after a run and keeps older, incomplete campaign evidence separate.

## Canonical funnel

Every raw generation has exactly one candidate/event ID and these ordered tri-state fields:

```text
raw → parseable → AST-pass → runnable → target-valid → oracle-bearing
    → reproducible → non-duplicate → minimized → stable/nightly → promoted
```

A value is `true`, `false`, or `null` (not logged). `null` is never changed to `false`, and counts from campaigns with different denominators are never pooled. A later stage cannot pass after an earlier stage fails. Promotion additionally requires `anomaly_present=true`.

The runner aliases accepted by the normalizer include `parses`, `target_call_present`, `oracle_present`, and `reproduced`. `non_duplicate` is derived only when `duplicate_check_completed=true`; `stable_nightly` passes only when both statuses pass.

## Commands

Run from this directory with Python 3.10 or later:

```bash
python vn_funnel.py normalize /path/to/events.jsonl normalized_events.jsonl
python vn_funnel.py summarize normalized_events.jsonl funnel_report.json --csv funnel.csv
python vn_funnel.py import-benchmark /path/to/events_latest.jsonl imported_run
python vn_funnel.py validate-normalized imported_run/normalized_events.jsonl --output validation.json
python vn_funnel.py validate-ledger candidate_ledger.jsonl --output candidate_ledger_summary.json
python build_archive_report.py
python -m unittest discover -p "test_*.py" -v
```

`candidate_ledger.jsonl` replaces narrative candidate counting with one structured row per candidate/family. Each row records reproduction, duplicate checking, minimization, stable testing, nightly/main testing, promotion, disposition, and its evidence source.

## Append-only candidate verification

`candidate_workflow.py` turns the static ledger into a hash-chained audit log. Importing the historical ledger preserves its statuses but marks them `verified_in_audit=false`; a legacy `yes` is not enough to pass the promotion gate. Each new partial/pass/fail update requires an existing evidence artifact, its computed SHA-256, a timezone-aware timestamp, tool name, and tool version.

```bash
python candidate_workflow.py import-ledger candidate_ledger.jsonl candidate_audit.jsonl
python candidate_workflow.py update candidate_audit.jsonl CAND-ID reproducible passed \
  --artifact repro_result.json --tool pytest --tool-version 8.4.1
python candidate_workflow.py verify candidate_audit.jsonl --output candidate_state.json
python candidate_workflow.py promote candidate_audit.jsonl CAND-ID \
  --artifact reviewer_decision.json --tool manual-review --tool-version protocol-v1
```

Promotion is allowed only when reproducibility, non-duplicate review, minimization, stable testing, and nightly/main testing each have an audited `passed` event. `pending`, `partial`, `failed`, `not_applicable`, a legacy state without an audit event, a missing/tampered artifact, a broken event hash, or an illegal transition blocks promotion. The tool only records supplied evidence; it does not run nightly tests or upgrade any candidate automatically.

`import-benchmark` is the adapter for the 120-API notebook's `events.jsonl`/`events_latest.jsonl`. It writes normalized JSONL, a flat event-ledger CSV, a JSON/CSV funnel report, and an input-hash manifest. The benchmark currently provides evidence through `oracle_bearing`; therefore `reproducible`, `non_duplicate`, `minimized`, `stable_nightly`, and `promoted` remain null unless those fields are explicitly present in a source event. Runnable or target-valid code is never treated as reproduction or novelty evidence.

The contracts are `normalized_event.schema.json`, `candidate_ledger.schema.json`, and `candidate_audit.schema.json` (JSON Schema 2020-12). The standard-library validators are fail-closed for required fields, invalid tri-state/status values, non-monotone stages, promoted rows without anomaly evidence, malformed provenance, duplicate IDs, broken audit chains, and changed evidence artifacts. Every imported event records the source-file SHA-256, 1-based source row, run signature, and importer version; the import manifest repeats the source hash and run/baseline counts.

## Archived evidence boundary

`archive_campaign_counts.csv` transcribes the counters already reported in Section 4.5. It intentionally contains blanks because those campaigns predate the unified schema. `atlas_snapshot.json` records corpus size but leaves Atlas intervention outcomes as `null`. `build_archive_report.py` derives only defensible coverage, ledger, and corpus statistics from these files.

`testdata/complete_events.jsonl` is synthetic unit-test data and must not be cited as an experimental result.

## Two-seed checkpoint and compact verification

The complete seed-3407 and seed-7711 shards are imported without upgrading any
post-oracle field:

```powershell
python TrDGL-FuzzVn_paper/experiments/vn_funnel/vn_funnel.py import-benchmark `
  TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/events.combined.jsonl `
  TrDGL-FuzzVn_paper/experiments/vn_funnel/two_seed_checkpoint
```

Assertion signals and semantic probes are regenerated with the reviewed
decision ledger supplied explicitly:

```powershell
python TrDGL-FuzzVn_paper/experiments/vn_funnel/triage_assertion_signals.py `
  --input TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/events.combined.jsonl `
  --documentation TrDGL-FuzzVn_paper/experiments/benchmark_120/checkpoints/seed7711_480/documentation_snapshot.json `
  --output-dir TrDGL-FuzzVn_paper/experiments/vn_funnel/two_seed_checkpoint/triage `
  --decisions TrDGL-FuzzVn_paper/experiments/vn_funnel/two_seed_checkpoint/triage/triage_decisions.jsonl `
  --replay-api torch.compile
```

For routine handoff, run only the compact fail-closed verifier and send its
single output line. Detailed files need inspection only on failure:

```powershell
python TrDGL-FuzzVn_paper/experiments/vn_funnel/verify_two_seed_checkpoint.py
```
