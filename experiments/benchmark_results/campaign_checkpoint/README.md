# Immutable campaign checkpoint (seed 3407)

This directory preserves one complete generation-seed shard at **480 / 480**
events for seed 3407 (**480 / 2,400** for the five-seed campaign). It is
empirical campaign-checkpoint evidence, but it is not a complete or paper-ready
campaign result. `summary.json` therefore has
`ready_for_paper_result=false` and lists three blockers: missing full-campaign
events, incomplete five-seed B2/B3 pairing, and missing seed shards.

The canonical raw stream and run manifest are retained in
`benchmark_120/checkpoints/seed3407_480/`; the campaign index points directly
to its executed notebook for the shard-equivalence gate:

- append-only raw event stream: SHA-256
  `55e61acab475d370f6261be2041fdbb74ef5f06bd8197044df587c60a4f4af09`;
- run manifest: SHA-256
  `0e54a8546c34ad6087d7e7567c426333eb8d38b4968e45da356f8bbf779399c3`;
- executed notebook: SHA-256
  `048aafd52ab8098a58abc310c32819977dbcc80374022a5e1f07baf2cbf4f51a`.

The campaign collector verified that the executed notebook has the same
canonical code hash and runner version as the frozen notebook, and that the
manifest's pinned base/tuned models, decoding defaults, and subprocess timeout
match the frozen notebook. The remaining files are deterministic derivatives.

Regenerate the checkpoint from the workspace root:

```powershell
python TrDGL-FuzzVn_paper/experiments/benchmark_results/collect_benchmark_campaign.py `
  TrDGL-FuzzVn_paper/experiments/benchmark_results/campaign_checkpoint/campaign_shards.json `
  TrDGL-FuzzVn_paper/experiments/benchmark_results/campaign_checkpoint/summary.json `
  --notebook TrDGL-FuzzVn_paper/experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb `
  --combined-events TrDGL-FuzzVn_paper/experiments/benchmark_results/campaign_checkpoint/events.combined.jsonl `
  --cells-csv TrDGL-FuzzVn_paper/experiments/benchmark_results/campaign_checkpoint/baseline_group_seed.csv `
  --coverage-csv TrDGL-FuzzVn_paper/experiments/benchmark_results/campaign_checkpoint/event_coverage.csv `
  --report-md TrDGL-FuzzVn_paper/experiments/benchmark_results/campaign_checkpoint/checkpoint.md
```

Do not replace or relabel the synthetic files in `validation_output/`; they
remain `validation_only` contract evidence.
