# Immutable two-seed campaign checkpoint

This directory preserves two complete generation-seed shards at **960 / 2,400**
events: seeds 3407 and 7711, each with 120 events for B0, B1, B2, and B3.
It is empirical campaign-checkpoint evidence, but it is not a completed or
paper-ready five-seed campaign result. `summary.json` therefore records
`ready_for_paper_result=false` and the expected blockers for 1,440 missing
events, 360 missing B2/B3 pairs, and three missing seed shards.

The canonical raw streams, manifests, and executed notebooks remain in the two
immutable checkpoint directories under `benchmark_120/checkpoints/`. The
campaign collector verified both shards against the same frozen notebook code,
runner version, model pins, decoding configuration, subprocess timeout, and
environment contract. It also verified:

- 960 unique persisted events and no metadata mismatch;
- 240 complete B2/B3 prompt pairs out of 600, with zero prompt-hash mismatch;
- 120 pairs in each observed A/B order;
- complete per-baseline counts of 240 for the two declared seeds;
- combined event-stream SHA-256
  `03bbd2b8d20901e521ab7bfbc3a4816a770c657c65ac32c79d058af159de5a8d`.

The diagnostic paired outcomes are retained exactly as observed. In particular,
B3 has zero oracle-bearing programs in these 240 pairs, so this checkpoint must
not be used to claim that fine-tuning improved B2.

Regenerate all deterministic derivatives from the workspace root:

```powershell
python TrDGL-FuzzVn_paper/experiments/benchmark_results/collect_benchmark_campaign.py `
  TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/campaign_shards.json `
  TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/summary.json `
  --notebook TrDGL-FuzzVn_paper/experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb `
  --combined-events TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/events.combined.jsonl `
  --cells-csv TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/baseline_group_seed.csv `
  --coverage-csv TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/event_coverage.csv `
  --report-md TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/checkpoint.md
```

The older `campaign_checkpoint/` remains the stable seed-3407 checkpoint used by
the current paper/evidence matrix until the downstream 960-event analyses are
rebuilt in dependency order.
