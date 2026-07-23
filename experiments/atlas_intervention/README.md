# Paired DL-Issue Atlas effectiveness protocol

This directory measures requirement R9 without treating the paper-reported
Atlas corpus size as an effectiveness result. It separates two interventions:

1. **Duplicate triage.** Replay the identical candidate summary with Atlas
   retrieval enabled and disabled. Both arms must share candidate-summary,
   model, decoding, generation-seed, harness, base-prompt, and effective-prompt
   hashes.
2. **Guided planning.** Regenerate from the same base prompt with the same
   model, decoding settings, generation seed, and harness. Only the enabled arm
   may add Atlas guidance, so its effective prompt and generated program may
   differ.

`pair_order` records which arm ran first. The campaign gate requires the counts
of `enabled_first` and `disabled_first` pairs to differ by at most one within
each intervention. This guards against warm-cache and temporal order effects.
For guided planning, `atlas_guided=true` is accepted only when the effective
prompt hash differs from the base prompt and a retrieved cluster is recorded;
an unchanged prompt cannot be counted as an Atlas-guided generation.

## Reported outcomes

The collector reports, separately by intervention and arm:

- retrieved-cluster matches;
- duplicates detected and rejected;
- independently verified retrieval precision, with unknown verification kept
  out of its denominator;
- candidates whose generation was actually Atlas-guided;
- reproduced and unique reproduced candidates per 1,000 generations;
- total/mean triage time and paired enabled-minus-disabled time;
- enabled-only duplicate decisions/rejections and enabled-only reproduced
  candidates.

A known duplicate verdict requires both a verification method and the hash of
its evidence artifact. A reproduced planning candidate requires hashes for its
reproducer and unique signature. Missing evidence remains `null`; it is never
converted to `false` or a successful count.
Detection and rejection are deliberately separate: a retrieval hit may be
counted as a detected duplicate while verification is unknown or negative, but
`rejected_as_duplicate=true` is accepted only after positive independent
verification. This prevents an Atlas false positive from being reported as a
successful de-duplication.

## Source and fail-closed gates

Paper-ready output requires all of the following:

- events labeled `campaign`;
- the raw Atlas dataset passed with `--atlas-dataset`;
- a separate source manifest passed with `--atlas-manifest`;
- manifest filename, SHA-256, byte count, record count, and campaign provenance
  matching the raw file;
- every enabled event using that verified dataset SHA-256;
- complete enabled/disabled pairs for both interventions;
- one model, decoding configuration, and harness;
- the same model/decoding/seed/harness/base input inside every pair;
- counterbalanced pair order and all five declared seeds;
- no pending or error event.

The collector does **not** trust the two presence booleans in
`vn_funnel/atlas_snapshot.json`; it verifies actual paths and bytes. That audit
currently says both the raw Atlas and independent manifest are absent, so the
checked result must remain `ready_for_paper_result=false`.
`source_recovery_search.md` records the workspace filename/content search and
its scope boundary; it is evidence of local search, not proof that no external
copy exists.

`testdata/validation_events.jsonl` is a synthetic schema/contract fixture only.
Its hashes and counts must never be copied into the paper. The checked summary
has blockers for its validation label, absent raw Atlas, absent manifest, and
incomplete campaign seeds.

## Commands

Validate the current fail-closed fixture from this directory:

```powershell
python collect_atlas_intervention.py `
  testdata/validation_events.jsonl validation_output/summary.validation.json `
  --atlas-audit ../vn_funnel/atlas_snapshot.json `
  --required-seeds 3407,7711,12011,19001,27103

python -m unittest discover -s . -p "test_*.py" -v

# Regenerate summary + hashed validation-only bundle and rerun its tests
python build_validation_bundle.py
```

Run a real campaign after recovering/freezing Atlas source data:

```powershell
# Create the independent manifest from the recovered export. All provenance
# arguments must describe the actual export; the freezer computes bytes,
# record count, and SHA-256 and refuses an empty dataset.
python freeze_atlas_source.py `
  campaign/dl_issue_atlas.jsonl campaign/dl_issue_atlas.manifest.json `
  --format jsonl --snapshot-id <snapshot-id> --created-by <researcher> `
  --source-system <source-system> --export-command <exact-export-command>

python collect_atlas_intervention.py `
  campaign/events.jsonl campaign/summary.json `
  --atlas-audit ../vn_funnel/atlas_snapshot.json `
  --atlas-dataset campaign/dl_issue_atlas.jsonl `
  --atlas-manifest campaign/dl_issue_atlas.manifest.json `
  --required-seeds 3407,7711,12011,19001,27103
```

The source manifest must validate against `atlas_source_manifest.schema.json`.
Event and summary files validate against the two corresponding schemas in this
directory. Do not change `evidence_label` or the source-audit booleans merely to
clear a blocker; recover the underlying artifacts and rerun the collector.

`paper_method_snippet.tex` is a method-only paragraph ready for later inclusion.
It deliberately states the present evidence boundary and contains no synthetic
count or effectiveness claim.

## Two-seed checkpoint

The provisional `torch.compile` signal from the 960-event checkpoint is linked
in `two_seed_checkpoint/atlas_blocker_manifest.json`. Because the raw Atlas and
independent manifest are still absent, no enabled arm was run and all
effectiveness outcomes remain `null`. Verify this boundary with one compact
command:

```powershell
python TrDGL-FuzzVn_paper/experiments/atlas_intervention/verify_two_seed_atlas_checkpoint.py
```
