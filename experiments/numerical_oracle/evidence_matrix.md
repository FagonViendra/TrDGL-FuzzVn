# Numerical-oracle evidence matrix

Audit date: 2026-07-10. This audit distinguishes source result artifacts from
paper-only numbers and local protocol validation. Missing means “not evidenced,”
not zero.

## Current boundary

| Device | Mode | Forward | Gradient | Exact matched float32/float64 cells |
|---|---|---|---|---|
| CPU | eager | Five-seed local validation | Five-seed local validation | 120 designed clean/injected threshold cells measured |
| CPU | compiled | Local unsupported validation | Local unsupported validation | Unsupported on current Windows/PyTorch host; not measured |
| CUDA | eager | Five-seed local validation | Five-seed local validation | 120 designed clean/injected threshold cells measured |
| CUDA | compiled | Local unsupported validation; separate NVFP4 forward evidence | Local unsupported validation | Matched compiled cells unsupported; not measured |

The existing Blackwell campaign is real source evidence, but it is not the
requested matched factorial. It uses packed NVFP4 inputs, bfloat16 outputs, and
FP32/FP64 references. It therefore cannot fill float32/float64 *input* cells.

The new local checkpoint represents every requested fixed-threshold design
dimension across all five seeds. Of 480 events, 240 eager events are measured
and 240 compiled events are explicitly unsupported after one preflight per
device. Unsupported is a coverage blocker, not a zero effect.

## Located source evidence

- `blackwell_nvfp4_fuzz/results/nvfp4-crafted-validate-20260630-102927.analysis.json`:
  completed CUDA crafted run, 44,838 passes and zero findings.
- `blackwell_nvfp4_fuzz/results/nvfp4-tile-sweep-validate-20260630-103941.analysis.json`:
  completed CUDA tile sweep, 73,486 passes, zero findings, maximum relative L2
  0.0059334361 under the campaign's 0.035 threshold.
- `blackwell_nvfp4_fuzz/results/nvfp4-compile-repro-validate-20260630-212951.analysis.json`:
  one completed CUDA eager/compiled reproducer with explicit forward metrics
  and deterministic digests.
- `blackwell_nvfp4_fuzz/nvfp4_fuzz.py`: implements CUDA eager/compiled paths,
  FP64 reference/fallback logic, relative/absolute error, a 0.035 NVFP4
  threshold, and program-specific forward-bound calculations.
- `experiments/numerical_oracle/five_seed_local_checkpoint/diagnostic_manifest.json`:
  five-seed Windows/PyTorch 2.6.0+cu124 local diagnostic on an RTX 3050 Ti.
  CPU/CUDA eager has 0/120 clean false positives; injected delta `2e-4` is
  detected 40/40 at `1e-5`, 40/40 at `1e-4`, and 0/40 at `1e-3`.

These artifacts do not contain CPU results, gradient checks, ULP reporting, or
the fixed `1e-3`/`1e-4`/`1e-5` matched comparison requested by the supervisor.

## Paper-only claim

`main.tex` reports 29/30 certified injected defects, 28/30 detections at fixed
`1e-4`, and 0/20 clean false positives. No source certificate or fault-injection
result file was located in the current workspace. Those values remain
`paper_only` and are not imported into generated summaries.

## Runnable protocol

The new event schema records device, execution mode/backend, forward or
gradient check, input/reference dtype, seed, clean/injected control, fixed or
certified tolerance, absolute/relative/ULP error, result, duration, and
environment.

From `TrDGL-FuzzVn_paper`:

```powershell
python experiments/numerical_oracle/run_numerical_oracle_protocol.py `
  --output numerical_oracle_events.jsonl `
  --run-manifest numerical_oracle_run_manifest.json `
  --evidence-label campaign `
  --seeds 3407,7711,12011,19001,27103 `
  --devices cpu,cuda `
  --modes eager,compiled `
  --checks forward,gradient `
  --dtypes float32,float64 `
  --tolerances 1e-3,1e-4,1e-5 `
  --include-injected `
  --certified-bound VALUE_FROM_THEOREM_OR_CERTIFICATE `
  --certified-bound-source C:/path/to/certificate.json

python experiments/numerical_oracle/collect_numerical_oracle_results.py `
  numerical_oracle_events.jsonl numerical_oracle_summary.json
```

The local checkpoint can be checked without any GPU work:

```powershell
python experiments/numerical_oracle/verify_five_seed_local_checkpoint.py
```

`validation_output/summary.local.json` is a local CPU/eager smoke validation,
not a paper result. It covers one seed, forward/gradient, float32/float64,
clean/injected controls, ULP error, and all three fixed thresholds; it correctly
sets `all_factorial_dimensions_present=false`,
`certified_bound_present=false`, and `ready_for_paper_result=false`.

`validation_output/summary.local_cpu_eager_compiled.json` reruns the same local
validation with CPU eager and CPU compiled requested together. It records 48
events: 16 measured eager passes, 8 injected-control eager failures, and 24
compiled cells marked `unsupported` on the current Windows/PyTorch host. This
improves the engineering audit by making the compiled local boundary explicit,
but it still does not satisfy matched campaign coverage.

`five_seed_local_checkpoint/summary.local_factorial.json` supersedes those
engineering smokes for local coverage. All five seeds, both devices, both
checks, both dtypes, both controls, and all three fixed thresholds are present.
Its `all_factorial_dimensions_present=true` but
`all_factorial_dimensions_measured=false`, because all eight compiled
device/check/dtype dimensions are unsupported. It also has no sourced
certified-bound events, so `ready_for_paper_result=false`.

`--certified-bound` is deliberately optional and is never inferred from the
observations. It must be paired with `--certified-bound-source`; every certified
event records the source artifact's SHA-256. Otherwise certified fields remain
absent rather than being filled with a fixed tolerance.

Completion requires an immutable campaign-mode JSONL with the full matched
CPU/CUDA x eager/compiled x forward/gradient matrix, declared seeds/dtypes,
all fixed thresholds, certified-bound events, and environment/artifact hashes.
An observed but `unsupported`/`error` cell does not satisfy measured factorial
coverage. Every one of the five declared seeds must have all three fixed
thresholds in every matched factorial cell; any missing or unresolved cell
keeps `ready_for_paper_result=false`.
