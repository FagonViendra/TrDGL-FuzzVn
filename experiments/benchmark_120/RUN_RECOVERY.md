# Benchmark execution and recovery record

## Durable evidence

The benchmark is append-only. Historical seed-3407 recovery points are stored
under `checkpoints/seed3407_327/`, `checkpoints/seed3407_360/`, and
`checkpoints/seed3407_431/`. The complete immutable shards are
`checkpoints/seed3407_480/` and `checkpoints/seed7711_480/`, each with the event
ledger, run manifest, SHA-256 manifest, environment/model/decoding provenance,
and last event. The deterministic two-shard aggregation is stored separately in
`../benchmark_results/two_seed_checkpoint/` so the stable one-seed evidence used
by the current paper is not overwritten before downstream analyses are rebuilt.

Each shard expects 480 events (120 APIs times four baselines). Seeds 3407 and
7711 are complete, so the verified campaign checkpoint contains 960 / 2,400
events and 240 / 600 complete B2/B3 pairs with zero prompt-hash mismatches. The
full campaign still requires seeds 12011, 19001, and 27103 (1,440 events). Each
shard has its own run signature because selected task IDs are part of the
signature. Cross-shard aggregation therefore requires the campaign
index/equivalence gate rather than a single-signature concatenation.

## Resume procedure

1. Create a T4 session with the Colab CLI.
2. Set `TRDGL_AUTO_MOUNT_DRIVE=0`, `TRDGL_SEED_INDEX=0`,
   `TRDGL_MAX_TOKENS=600`, the output directory, and a cache directory.
3. Upload the latest verified checkpoint for the shard being resumed. The
   current complete checkpoints are
   `checkpoints/seed3407_480/events.checkpoint.jsonl` and
   `checkpoints/seed7711_480/events.checkpoint.jsonl`; historical seed-3407
   resume points such as `seed3407_431` are retained only for audit/recovery
   history. Upload the selected checkpoint as
   `<output>/events.jsonl`.
4. Execute `trdgl_fair_benchmark_120.ipynb`.
5. Download `events.jsonl`, `run_manifest.json`, and the executed notebook.
6. Verify event uniqueness, run signature, artifact hashes, and expected counts.

The notebook checkpoint logic ignores malformed trailing JSONL lines, but a
release artifact must pass the stricter benchmark, funnel, error-analysis, and
campaign-shard validators.

## Remaining-seed one-command runner

`run_remaining_campaign.py` is the current continuation entry point. From the
workspace root on Windows, run:

```powershell
python TrDGL-FuzzVn_paper/experiments/benchmark_120/run_remaining_campaign.py
```

The default command covers seed indices 1--4 (7711, 12011, 19001, and 27103)
sequentially in one reusable T4 session and safely recognizes the completed
seed-7711 handoff. The next unfinished shard is seed 12011. The runner executes
the exact frozen notebook without changing code cells or the benchmark
contract. Operational I/O is optimized by keeping the live append-only stream
on the Colab local SSD and
downloading a validated snapshot every 30 seconds. The default local SSD cache
and staged GGUF files are reused across seeds while the session survives. A
persistent Drive cache remains available through `--cache-mode drive`, with a
local fallback if mounting fails.

Before spending generation time, the launcher verifies the frozen notebook
byte/code hashes and compares the remote Python, PyTorch, CUDA, T4, NumPy,
pandas, and Hugging Face environment with seed 3407. Every downloaded snapshot
is rejected unless seed, task/API metadata, Latin order, baseline counts,
unique identities, raw-generation fields, and hashes match the frozen
manifest. Re-running the same command resumes from the latest accepted JSONL.

Live state is written outside the manuscript evidence path under
`tmp/trdgl_campaign_continuation/`. Each completed seed produces
`HANDOFF.txt`, `handoff_summary.json`, an executed frozen notebook, and
`trdgl_seed<seed>_handoff.zip`. Send the ZIP to the next analysis session; if
the launcher stops with an error, send `campaign_status.json` and
`campaign_progress.log` instead. Validate the launcher without requesting a
runtime with:

```powershell
python TrDGL-FuzzVn_paper/experiments/benchmark_120/run_remaining_campaign.py --self-test
```

## Historical seed-3407 auto-resume watcher

As of the 2026-07-09 recovery pass, the local watcher is intentionally
outside the manuscript evidence path and writes only short operational state:

- Script: `tmp/auto_resume_seed3407.py`.
- State: `tmp/seed3407_auto_state.json`.
- Log: `tmp/seed3407_auto_resume.log`.
- Local upload/download buffer: `tmp/seed3407_auto_events_backup.jsonl`.

During the July 9 recovery pass, the watcher seeded its local buffer from
`checkpoints/seed3407_431/events.checkpoint.jsonl`, retried creation of a T4
Colab session, uploaded the latest safe buffer as `<output>/events.jsonl`, ran
`trdgl_fair_benchmark_120.ipynb`, and downloaded `events.jsonl` periodically.
Its status file is the source for operational monitoring; the chat transcript
and long Colab tracebacks are not provenance.

That recovery pass completed seed 3407 and persisted all 480 JSONL rows. The
direct remote `events.jsonl` and watcher backup share SHA-256
`55e61acab475d370f6261be2041fdbb74ef5f06bd8197044df587c60a4f4af09`, and the
frozen `seed3407_480` manifest records B0/B1/B2/B3 counts of 120 each. Rows
432--480 no longer need rerun for seed 3407. Seed 7711 subsequently completed
all 480 rows with event SHA-256
`8a27a2280f550887be0cf031f900ad1aec16a3441719c17683185c027315d6bc`.
The remaining campaign gap is now three unfinished generation seeds (1,440
events), not missing rows in either immutable completed shard.

## Relevant committed foundations

- `f5886f2c`: fair Colab runner, Vn funnel, candidate ledger, and replay ablation.
- `d90130a5`: hardened generation-error validation foundation.
- `b2a508fe`, `507c7a01`, `8571bc50`: disagreement, failure-catalog, and reviewer-consensus diagnostics.

The workspace is shared with unrelated projects, so paper commits are
path-scoped. Unrelated commits in global `git log` are not experimental
provenance for TrDGL-FuzzVn.

## Evidence limits

An incomplete checkpoint can validate the harness, resume logic, schemas, and
diagnostic tooling. It cannot support final four-baseline rates, base-versus-
tuned claims, order-balanced comparisons, Vn promotion yield, Atlas causal
effectiveness, or a completed ablation result.
