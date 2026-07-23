# Reproducibility release checklist

This checklist is a publication gate, not evidence that the current campaign is
complete. A missing value remains `null`/`pending`; it is never replaced by
zero or inferred from prose.

## Freeze and identify the run

- [ ] Copy the final run directory to immutable/versioned storage before aggregation.
- [ ] Preserve `run_manifest.json`, the raw JSONL event stream, and baseline summary.
- [ ] Verify the notebook SHA-256 and embedded benchmark-manifest SHA-256.
- [ ] Verify one compatible run signature and the five declared decoding seeds.
- [ ] Verify 2,400 raw events are also 2,400 unique `(baseline, task_id)` identities.
- [ ] Verify zero duplicate identities, zero unidentified events, and exactly 600 unique events for each of B0--B3.
- [ ] Verify all B2/B3 pairs have identical prompt hashes and report order balance.

## Freeze the environment and cost record

- [ ] Record OS, Python, PyTorch, CUDA, driver, GPU name/count/memory, and all model revisions/hashes.
- [ ] Publish a lockfile or container image digest and the exact reproduction command.
- [ ] Record wall-clock span, setup-time policy, generation/subprocess time, throughput, peak VRAM, CPU-hours, and GPU-hours.
- [ ] Record subprocess timeout, decoding parameters, and every host/model seed backend.

## Package evidence safely

- [ ] Include generated benchmark, funnel, ablation, error, Atlas, numerical-oracle, candidate-ledger, and reproducibility summaries.
- [ ] Retain raw inputs beside every generated summary and publish SHA-256 hashes.
- [ ] Exclude credentials, browser/HAR metadata, private tokens, unrelated files, and non-redistributable checkpoints.
- [ ] Confirm manifests contain workspace-relative paths and no local username.
- [ ] Assign a stable archival URL/DOI and record the license for code, data, and model-derived artifacts.

## Validate before manuscript refresh

Run from `TrDGL-FuzzVn_paper`:

```powershell
python experiments/reproducibility/collect_artifact_manifest.py `
  --mode campaign `
  --run-dir C:/path/to/frozen_run `
  --environment-lock C:/path/to/environment.lock `
  --public-artifact-url-or-doi https://doi.org/... `
  --output C:/path/to/frozen_run/artifact_manifest.json

python -m unittest discover -s experiments/reproducibility -p "test_*.py" -v
```

- [ ] Confirm `ready_for_release=true`; inspect every missing field if false.
- [ ] Recompute all manuscript tables from the frozen evidence, compile twice, and visually inspect the PDF.
- [ ] Update the abstract only after its numbers match a hashed machine-readable result.

## Current state

The checked local and four-event smoke manifests validate plumbing only. Both
correctly set `ready_for_release=false`; neither is a substitute for the frozen
2,400-event campaign and public archive.
