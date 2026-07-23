# Benchmark result and coverage collector

This collector reads the append-only JSONL emitted by the frozen 120-API
notebook. It extracts and verifies the embedded manifest instead of maintaining
a second API list.

Outputs are:

- one JSON summary with completion, fairness, runtime, and throughput gates;
- one 2,400-row coverage ledger (`120 APIs x 5 seeds x 4 baselines`) whose
  missing-event metric fields remain empty;
- one 200-row CSV (`4 baselines x 10 groups x 5 seeds`) with expected/observed
  events and parseable, AST-pass, runnable, target-valid, and oracle-bearing
  counts/rates.
- an optional compact Markdown checkpoint, generated from the same hashed
  stream, that keeps incomplete results visibly outside the paper-ready gate.

Missing cells retain `observed_events=0`, metric rates `null`, and
`complete=false`. The complete campaign gate requires all 2,400 unique events,
the exact frozen task metadata, one selected run signature, 600 complete B2/B3
pairs with equal prompt hashes, the frozen 300/300 A/B order, and logged model
sampler seeds for every LLM event. It also requires every event to retain a raw
generation and rejects per-baseline model-label drift. `campaign_span_seconds`
includes idle/restart gaps; event-wall throughput is reported separately.

For base-vs-tuned analysis, the summary forms B2/B3 pairs only when task ID,
prompt hash, and A/B order metadata agree. For parseability, AST pass,
runnability, target validity, and oracle bearing it records the complete paired
2x2 table, B3-minus-B2 rate difference, and exact two-sided McNemar p-value.
The same paired summaries are stratified by API group and generation seed so
group heterogeneity and seed sensitivity can be reported without comparing
unpaired marginals.
Partial paired statistics remain checkpoint evidence until the full 600-pair
gate passes.

`logical_baseline_order` is the notebook's frozen Latin rotation, not a
constant list. The collector reconstructs the exact order for every API/seed
task, rejects mismatches, and reports the expected 150 placements for every
baseline-position cell. It also exposes completion independently for all five
seeds; a finished 480-event seed shard remains incomplete against the
2,400-event campaign denominator.

Current checkpoint validation:

```powershell
python collect_benchmark_results.py `
  ../../../tmp/colab_smoke_4baseline/events_latest.jsonl `
  validation_output/summary.validation.json `
  --notebook ../benchmark_120/trdgl_fair_benchmark_120.ipynb `
  --cells-csv validation_output/baseline_group_seed.validation.csv `
  --coverage-csv validation_output/event_coverage.validation.csv `
  --report-md validation_output/checkpoint.validation.md `
  --evidence-label validation_only

python -m unittest discover -s . -p "test_*.py" -v
```

When an executed notebook and the downloaded JSONL disagree, audit the
provenance before freezing a shard:

```powershell
python audit_checkpoint_provenance.py `
  ../../../tmp/seed3407_progress.jsonl `
  ../../../tmp/seed3407_shard/run_manifest.json `
  validation_output/seed3407.live.provenance.json `
  --notebook ../benchmark_120/trdgl_fair_benchmark_120.ipynb `
  --executed-notebook ../benchmark_120/trdgl_fair_benchmark_120_output.ipynb `
  --run-signature <sha256>
```

This gate deliberately treats validated, persisted JSONL rows as the evidence
ceiling. A notebook transcript such as `480 / 480` proves that its runtime
reached that point, but cannot replace raw generations that were not downloaded
and frozen. For seed 3407, all 480 raw rows are now frozen and match the
transcript. The audit remains checkpoint evidence because the other four seed
shards are absent, not because seed 3407 has an unpersisted tail.

If an append-only stream contains multiple run signatures, pass the intended
one with `--run-signature`. A malformed final non-newline record is treated as
an interrupted tail and ignored, but it blocks completion; malformed JSON
anywhere else fails immediately. The current four-event checkpoint is a
validation input, not a benchmark result.

## Five independently resumed seed shards

`run_signature` includes the notebook's selected task IDs, so five
`RUN_ONLY_SEED` runs correctly have five different signatures. Do not concatenate
them and pretend that the signatures are equal. Preserve, for every seed:

- its append-only events JSONL;
- its `run_manifest.json`;
- its executed notebook (`.ipynb`) containing the exact code cells used.

Create an index conforming to `campaign_shard_index.schema.json`, with one entry
per seed and paths relative to the index. Then run:

```powershell
python collect_benchmark_campaign.py `
  campaign/campaign_shards.json campaign/summary.json `
  --notebook ../benchmark_120/trdgl_fair_benchmark_120.ipynb `
  --combined-events campaign/events.combined.jsonl `
  --cells-csv campaign/baseline_group_seed.csv `
  --coverage-csv campaign/event_coverage.csv `
  --report-md campaign/checkpoint.md
```

The multi-shard gate compares each executed notebook's canonical code-cell hash
and `RUNNER_VERSION` with the frozen notebook. It also requires one unique
declared seed per shard, the exact frozen API/task set, a matching manifest and
event signature, 120 selected tasks, and identical normalized run manifests.
It separately extracts the frozen base/tuned model specifications, decoding
defaults, and subprocess timeout from notebook literals and checks every shard
against them. This prevents a mutually consistent set of five shards from
passing when all five drifted from the frozen experiment configuration.
Each shard manifest must also preserve a timezone-qualified creation time,
valid manifest/documentation/signature hashes, a non-empty package inventory,
and the concrete Python, GPU, and event-log provenance fields.
The normalized comparison includes benchmark/documentation hashes, PyTorch,
CUDA, Python, packages, GPU, base/tuned model revisions and hashes, decoding,
and subprocess timeout; only creation time, event path, signature, and selected
task count are excluded. Any drift fails before aggregation. Distinct signatures
are accepted only after this equivalence proof.

Run `python build_validation_bundle.py` to regenerate the validation-only
bundle. Its five-shard campaign is synthetic contract testing, never empirical
benchmark evidence.
