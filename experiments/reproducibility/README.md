# Reproducibility and artifact manifest

This directory implements requirement R10 without treating the current laptop
as the Colab campaign runtime. The JSON Schema is
`artifact_manifest.schema.json`; `collect_artifact_manifest.py` hashes the
frozen notebook and embedded API manifest, inventories environment/library
versions, and aggregates a supplied run directory.

## Evidence modes

- `local_validation` verifies the collector, local environment, notebook JSON,
  embedded 120-API manifest, and checksums. Run signature, campaign timing,
  throughput, resource-hours, and run artifacts remain `null`/`pending`.
- `campaign` requires a real `run_manifest.json`. If an event stream exists,
  the collector accepts exactly one run signature and derives event-span
  timing, generation count, executed subprocess count, seeds, and throughput.
  Completeness uses unique `(baseline, task_id)` identities, requires balanced
  B0--B3 counts, and reports duplicate or unidentified rows separately; raw
  line count alone can never satisfy the release gate.
  The run's benchmark ID/hash must match the frozen notebook. Base/tuned model
  revisions and file hashes, decoding settings, subprocess timeout, benchmark
  execution command, and documentation hash are copied only from the supplied
  run manifest; missing fields stay pending.
  Event-span timing includes gaps between persisted events but excludes setup
  before the first event. GPU/CPU hours and peak VRAM remain pending unless the
  supplied run manifest explicitly records them.

Neither mode downloads data or invents a missing value. `null` means “not
evidenced,” never zero. A present artifact always receives its actual byte size
and SHA-256; a missing artifact receives neither.

## Commands

From `TrDGL-FuzzVn_paper`:

```powershell
python experiments/reproducibility/collect_artifact_manifest.py `
  --mode local_validation `
  --output experiments/reproducibility/validation_output/artifact_manifest.local.json

python experiments/reproducibility/collect_artifact_manifest.py `
  --mode campaign `
  --run-dir C:/path/to/benchmark_120_output `
  --environment-lock C:/path/to/environment.lock `
  --public-artifact-url-or-doi https://doi.org/... `
  --output C:/path/to/benchmark_120_output/artifact_manifest.json

python -m unittest discover -s experiments/reproducibility -p "test_*.py" -v
```

The environment lock/container-description file and public archival URL/DOI
have dedicated fields; when present, the lock is hashed like every other
artifact. Additional release files can be hashed with repeated `--artifact PATH` flags.
Paths inside the workspace are stored relative to the workspace root; external
files use `external/<basename>` and remain identifiable by SHA-256. The manifest
records `workspace_root` rather than an absolute host path, sanitizes absolute
command arguments, and records only the Python executable name, avoiding
accidental username leakage.

## Current validation boundary

`validation_output/artifact_manifest.local.json` is intentionally not a
campaign result. It verifies the 120-API/10-group/five-seed embedded benchmark
and records the collector host, while the following remain pending:

- run manifest, raw event stream, and baseline summary;
- run signature, campaign start/end/duration, and throughput;
- benchmark execution command plus complete base/tuned model and decoding provenance;
- GPU/CPU hours and a campaign driver record;
- environment lock or container digest;
- public artifact URL or DOI.

The manifest sets `ready_for_release=false` until every required field is
evidenced. The exact missing-field list is machine-readable under
`completeness.missing_fields`.

The publication workflow and data-hygiene checks are enumerated in
`RELEASE_CHECKLIST.md`.

`validation_output/artifact_manifest.smoke.json` exercises campaign-mode
aggregation against the four-event smoke directory. It records one selected
task as complete while separately setting `full_benchmark_complete=false`, so
the fixture cannot be mistaken for the required 2,400-event result.
