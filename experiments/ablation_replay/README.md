# Same-corpus ablation replay

This directory implements the controlled component ablation requested for
TrDGL-FuzzVn. It deliberately contains one runnable script rather than another
generation notebook: the 120-API notebook generates and records programs once;
this script consumes its append-only `events.jsonl` without sampling again.

## Fair comparison contract

- The default replay corpus is B3 (the tuned model under the full prompt).
- `full`, `no_ast`, `no_oracle`, `no_vn`, and `no_atlas` receive the exact same
  event IDs, extracted programs, true decoding seeds, and raw-output hashes.
- The script records and verifies one corpus SHA-256. It aborts on duplicate
  event IDs, a raw-output hash mismatch, or missing decoding seeds. If an
  append-only log contains multiple run signatures, select exactly one with
  `--run-signature` rather than mixing runs.
- Syntax parsing and the immutable host-safety screen remain active in every
  condition. `no_ast` removes the import allow-list, suppressed-broad-exception,
  and size checks; exact target validation remains the later `target-valid`
  stage. It does not grant generated code file, network, or process access.
- Missing reproduction, minimization, duplicate, or stable/nightly evidence is
  `pending`, never silently converted to `false` or zero.
- `promoted_counterfactual` means eligible under the named gate policy. It is
  not a confirmed PyTorch bug and must not be reported as one.
- Atlas replay evaluates duplicate triage on the same candidate summaries.
  Atlas-guided *planning* changes which programs are generated and therefore
  requires a separate generation intervention; it cannot be reconstructed by
  replaying a fixed corpus.
- Fine-tuning is not a downstream gate. The script only audits whether B2 and
  B3 were regenerated as paired API/seed examples with identical full-prompt
  hashes. A “no fine-tuning” number must come from those B2 generations, never
  by relabeling B3 output.

## Run

On Colab or locally after the benchmark has produced `events.jsonl`:

```bash
python replay_ablation.py \
  --events /content/drive/MyDrive/TrDGL-FuzzVn/benchmark_120_v1/events.jsonl \
  --out /content/drive/MyDrive/TrDGL-FuzzVn/benchmark_120_v1/ablation_replay
```

If a frozen Atlas export is available, provide JSONL rows containing a
`fingerprint` (or `failure_signature`) and `cluster_id`:

```bash
python replay_ablation.py --events events.jsonl --atlas atlas.jsonl --out results
```

The exact-fingerprint adapter is intentionally conservative. A semantic Atlas
retriever may write `atlas_checked`, `atlas_duplicate`, and
`duplicate_cluster` into the event ledger instead; those decisions are replayed
when `--atlas` is omitted.

Run the zero-dependency deterministic smoke test with:

```bash
python replay_ablation.py --self-test
```

## Inputs needed after generation

The generator already supplies `baseline`, `task_id`, `api`,
`generation_seed`, `prompt_sha256`, `raw_output`, `extracted_code`, and runtime
fields. Candidate triage must add these tri-state fields to the same ledger:

```text
anomaly_triggered, reproduced, minimized,
atlas_checked, atlas_duplicate, duplicate_cluster,
stable_status, nightly_status
```

Absent fields remain pending. The output bundle contains:

- `ablation_manifest.json`: input-ledger, replay-script, frozen-corpus, and
  per-condition hashes; policy version; fairness assertion; and fine-tuning
  regeneration audit;
- `ablation_decisions.jsonl`: event-by-condition gate decisions without raw code;
- `ablation_summary.csv`: pass/fail/pending counts at every funnel stage;
- `ablation_table.tex`: compact paper-ready counterfactual promotion table;
- `fine_tuning_pairs.csv`: B2/B3 API-seed-prompt pairing audit.

The funnel is reported as raw, parseable, AST-pass, runnable, target-valid,
oracle-bearing, reproducible, non-duplicate, minimized, stable/nightly-known,
and counterfactually promoted. Reproducibility additionally requires an anomaly
signal even though that prerequisite is not shown as a separate funnel row.
In condition-specific summaries, an ablated stage is a pass-through gate: for
example, `no_oracle` can have an oracle-gate count even when the source program
does not contain an oracle. The decision JSONL retains observed AST/oracle
properties separately, so gate acceptance is never confused with code quality.

### Event schema

| Field | Type | Requirement and meaning |
|---|---|---|
| `run_signature` | string | Required when the append-only log contains more than one run; replay selects exactly one. |
| `baseline` | `B0`--`B3` | Required. Component replay defaults to B3; B2/B3 form the regenerated fine-tuning contrast. |
| `task_id` | string | Required unless API plus seed uniquely identifies the event. |
| `api` | string | Exact dotted target API. |
| `generation_seed` | integer | Required sampler seed, not merely a task-selection seed. |
| `seed_backend` | string | Must prove sampler plumbing, e.g. `...completion(seed)`; an explicit `decoding_seed_applied=true` is also accepted. |
| `prompt_sha256` | SHA-256 | Required for a fair B2/B3 pairing audit. |
| `raw_output` | string | Original immutable generation. Its recorded SHA-256 is verified when present. |
| `extracted_code` | string | Deterministically extracted Python program used by the common harness. |
| `runnable` | boolean/null | Exit-zero result from the one common subprocess execution; null is pending. |
| `anomaly_triggered` | boolean/null | A real crash/differential/oracle signal, not a generic malformed-program exception. |
| `reproduced`, `minimized` | boolean/null | Candidate-ledger states. Null means pending. |
| `atlas_checked`, `atlas_duplicate` | boolean/null | Whether duplicate triage completed and its decision. |
| `duplicate_cluster` | string/null | Canonical Atlas cluster when matched. |
| `stable_status`, `nightly_status` | string/null | Any non-pending label counts as classified; the label itself is retained in the source ledger. |

The parser accepts legacy aliases documented in the source, but new campaigns
should emit the canonical names above. It fails closed on corrupt hashes,
duplicate event IDs, mixed run signatures, missing seeds, or seeds that were not
proved to reach the model sampler.

### CLI contract

```text
--events PATH          append-only JSONL event ledger (required)
--out PATH             output bundle directory (required)
--baseline B3|ALL      B3 for scientific component replay; ALL is schema smoke only
--run-signature SHA    mandatory if the ledger contains multiple signatures
--atlas PATH           optional frozen fingerprint-to-cluster JSONL snapshot
--evidence-label LABEL validation_only (default), diagnostic_checkpoint, or paper_candidate
--self-test            deterministic tests for tri-state and fail-closed behavior
```

`--baseline ALL` must not be reported as the tuned-pipeline ablation; it exists
only to validate legacy/mixed-baseline ledgers. The paper result uses B3.

`paper_candidate` is a provenance label, not an automatic validity claim. Use it
only after the B3 matrix and candidate-ledger fields are complete; all numerical
claims still require inspection of pending counts and the run manifest.

`diagnostic_checkpoint` is reserved for an incomplete but immutable campaign
checkpoint. Its generated table is explicitly captioned as non-final, so a
two-seed replay cannot be mistaken for the planned five-seed result.

## Current two-seed checkpoint

The checked collector replays complete shards 3407 and 7711 separately, then
aggregates their decisions after verifying configuration equivalence. This
preserves the rule against mixing distinct run signatures inside one replay:

```bash
python collect_two_seed_checkpoint.py
python verify_two_seed_checkpoint.py
```

Both commands print one compact JSON PASS line. The bundle is written to
`two_seed_checkpoint/`; its manifest locks every source and generated-artifact
hash. The verifier also enforces that unavailable Vn/Atlas effects remain
`null`, rather than being reported as zero.

## Checked artifact currently in this repository

`validation_output/` was generated from the four-baseline local smoke ledger on
2026-07-08. The ledger contains exactly one B0, B1, B2, and B3 event for
`torch.tensor` at decoding seed 3407. Component replay correctly selects the
single B3 event, and the pairing audit confirms one B2/B3 pair with the same
prompt hash. Its manifest is deliberately labeled `validation_only`: n=1 proves
schema compatibility, equal per-condition corpus hashes, and paper-table
generation, but it is not a research ablation result. The final command must use
the completed 120-API x 5-seed B3 ledger and a fresh output directory:

```bash
python replay_ablation.py --events events.jsonl --baseline B3 \
  --evidence-label paper_candidate --out final_output
```
