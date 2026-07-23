# Seed 3407 checkpoint (327/480)

This directory freezes an append-only recovery point for the first 120-API,
four-baseline shard. It is evidence for execution and recovery plumbing, not a
final experiment result.

- B0: 120/120
- B1: 104/120
- B2: 103/120
- B3: 0/120
- Run signature: `221b2ab2bb66e6110da76ea5cde39b20fb3613e8ee3527f8818a039e7b6d8475`

`checkpoint_manifest.json` records artifact hashes, pinned model revisions,
environment versions, decoding parameters, the last event, and the claim
boundary. Verify hashes before resuming. Copy `events.checkpoint.jsonl` to the
configured output directory as `events.jsonl`; the notebook will skip completed
`(baseline, task_id)` keys belonging to the same run signature.

Do not merge this shard with other seed shards solely by concatenating JSONL.
Use the campaign shard index in `experiments/benchmark_results/`, which checks
manifests, executed-notebook hashes, models, decoding, harness configuration,
and API/task coverage before accepting distinct per-seed run signatures.
