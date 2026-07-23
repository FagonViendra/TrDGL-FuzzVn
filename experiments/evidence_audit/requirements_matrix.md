# Experimental-requirement evidence audit

Audit date: 2026-07-10. Scope: the current workspace and paper working tree.
No external service, unmounted archive, or unpublished result is assumed.
Line numbers refer to the audited working tree; file hashes are frozen in
`requirements_matrix.json` so later edits can be detected.

Evidence rule: only persisted, inspectable artifacts count as measurements.
A plan, implementation, empty result cell, paper-only transcription, or null
field is never upgraded to a completed experiment. Paths are resolved from
`C:/Users/fagon/OneDrive/Documents/New project 2`.

## Executive result

| ID | Requirement | Status | Exact current boundary |
|---|---|---|---|
| R1 | 120 APIs across multiple PyTorch groups | **Partial** | Immutable campaign checkpoint has 480/2,400 events: one complete seed shard. |
| R2 | Four baselines and related comparators | **Partial** | Latest persisted stream has B0=B1=B2=B3=120; no full five-seed campaign/external rerun. |
| R3 | Larger, multi-seed, same-harness base-vs-tuned | **Partial** | Fair 600-pair design exists; real checkpoint has 120 complete B2/B3 pairs with zero prompt mismatch. |
| R4 | AST/oracle/Vn/Atlas/fine-tuning ablation | **Partial** | Replay is implemented; checked result is validation-only B3 n=1. |
| R5 | Raw-to-promoted Vn funnel | **Partial** | Schema/importer/report exist; no real campaign has every stage. |
| R6 | Per-candidate verification ledger | **Done (reporting)** | Five rows explicitly say yes/no/partial/pending; verification itself remains incomplete. |
| R7 | Generation-error analysis | **Partial** | v19 analyzer covers all 480 events in the complete seed-3407 shard; four seeds/manual accuracy audit remain. |
| R8 | Numerical-oracle matrix | **Partial** | Certified-vs-1e-4 evidence exists; full device/mode/gradient/threshold matrix does not. |
| R9 | Atlas effectiveness | **Partial** | Paired protocol and fail-closed tests exist; raw Atlas and real duplicate/guidance measurements remain absent. |
| R10 | Reproducibility/runtime/artifact | **Partial** | Raw JSONL and the 480-event transcript now match; complete five-seed bundle/container/public archive remain absent. |

Count: **1 done, 9 partial, 0 missing**.

Strict completion is therefore **10% (1/10)**. All ten requirements have some
inspectable evidence, but the audit deliberately gives no invented fractional
credit to partial items; “100% started” is not “100% complete.”

The common blocker is not code structure. It is the absence of a complete
120-API x 5-seed x 4-baseline campaign (2,400 events) across five independently
signed, configuration-equivalent seed shards. An immutable real checkpoint preserves
all 480 events from the seed-3407 slice, and the executed notebook transcript
matches that persisted JSONL. The remaining evidence gap is the other four seed
shards (1,920 events), not an unpersisted tail of seed 3407.

## Audit validation

- The canonical JSON parses and contains exactly R1-R10.
- Its status count recomputes to 1 done, 9 partial, and 0 missing.
- All 53 evidence entries resolve to 29 unique paths; all 29 paths exist.
- All five artifact paths listed by the two `workspace_artifact` candidate
  rows exist. Existence does not independently prove a candidate verdict.
- Both benchmark notebooks parse as JSON; benchmark-result tests pass 19/19,
  the Vn suite passes 23/23, and the ablation replay self-test passes.
- Evidence-audit tests pass 3/3. The validator cross-checks the canonical
  campaign summary and provenance audit against the matrix: immutable
  480/2,400, B0/B1/B2/B3=120, transcript=480, evidence ceiling=480.
- Frozen SHA-256 values for the 22 primary audited artifacts recompute
  exactly. The JSON records those hashes so later paper/notebook edits are
  detectable.

Recheck with `python experiments/evidence_audit/validate_requirements_matrix.py`
from the paper directory. The validator fails on a missing evidence path,
changed audited hash, malformed notebook JSON, status-count mismatch, or
missing candidate artifact.

After paper edits are committed, run
`python experiments/evidence_audit/refresh_stable_hashes.py` before the
validator. The refresher refuses to write while `main.tex` is dirty, preventing
line locators and paper hashes from being frozen against a moving draft.

## Evidence and gaps

### R1 - Expanded benchmark: partial

Evidence:

- `experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb`, cells 0-3:
  frozen 120 APIs, 10 groups x 12 APIs, five seeds, 600 paired tasks, 2,400
  planned baseline events.
- `trdgl_fair_benchmark_120_output.ipynb`, cell 2 output: runtime API,
  task-matrix, Latin-order, and 300/300 B2/B3-order checks pass.
- `experiments/benchmark_results/campaign_checkpoint/summary.json` freezes a
  real 480/2,400-event checkpoint (480/480 in seed 3407), its source hashes,
  shard contract, and fail-closed blockers.
- `validation_output/seed3407.live.provenance.json` separately records 480
  validated raw rows and a matching 480/480 notebook transcript, with the
  persisted JSONL retained as the paper-evidence source.

Gap: one seed slice is complete and the other four are absent; there is no
600-event result per baseline, per-group rate table, or paired uncertainty.
Completion requires all 120 APIs x five seeds with every shard signature and
the cross-shard configuration-equivalence proof retained.

### R2 - Baselines: partial

Evidence:

- Benchmark notebook cells 6/8/10 implement B0 typed-template, B1 minimal
  base, B2 full-prompt base, and B3 tuned generation in one runner.
- The immutable campaign checkpoint records B0=B1=B2=B3=120 with
  explicit full-campaign denominators.
- `main.tex:654-665` defines the baselines and explicitly states that no
  compatible external method was rerun under the final schema.

Gap: finish B0-B3 on the full matrix. For an external comparator, first freeze
a compatible API/oracle subset; published headline bug counts are not a fair
baseline.

### R3 - Base versus tuned: partial

Evidence:

- Benchmark cells 2/4/10 enforce identical API-seed task IDs, full prompts,
  decoding/harness settings, and a 300/300 order balance.
- `campaign_checkpoint/summary.json:/fairness/paired_outcomes` records 120
  contract-eligible real B2/B3 pairs with zero prompt-hash or pair-order
  mismatches. This is a complete one-seed shard, not the planned five-seed
  effect estimate.
- The live provenance audit confirms that all 120 B2 rows and all 120 B3 rows
  are persisted; the remaining paired gap is 480 pairs across four seeds.
- `main.tex:704-721` reports the archived 40-API same-harness result but states
  that only one seed was archived.

Gap: generate 600 B2 and 600 B3 programs, then report paired API-seed effects
and confidence intervals. A frozen B3 output cannot be relabeled as no-tuning.

### R4 - Ablation: partial

Evidence:

- `experiments/ablation_replay/replay_ablation.py:26-27,300-438,531-620,
  622-704` implements full/no-AST/no-oracle/no-Vn/no-Atlas replay, tri-state
  pending, corpus-hash equality, B2/B3 pairing, and fail-closed tests.
- `validation_output/ablation_manifest.json` has equal hashes for all five
  conditions, but `evidence_label=validation_only` and `raw_event_count=1`.
- `main.tex:1569-1603` explicitly denies causal claims from this smoke result.

Gap: replay all 600 B3 events and populate real post-oracle states. Fine-tuning
requires regenerated B2/B3 outputs; Atlas-guided planning also requires a
generation intervention.

### R5 - Unified Vn funnel: partial

Evidence:

- `experiments/vn_funnel/README.md:5-36` defines the eleven-stage tri-state
  funnel, importer, schemas, validators, and provenance hashes.
- `archive_evidence_report.md:5-25` shows that no archived campaign logs every
  required stage.
- `main.tex:1519-1567` refuses to pool incompatible campaign denominators.

Gap: import the full event stream, then append reproduction, duplicate,
minimization, stable/nightly, and promotion evidence. Synthetic test rows do
not count as results.

### R6 - Candidate verification reporting: done

Evidence:

- `experiments/vn_funnel/candidate_ledger.csv`, rows 2-6: five candidate/family
  rows with reproduction, duplicate, minimization, stable, nightly, promotion,
  provenance, and disposition fields.
- `candidate_ledger.schema.json` validates the machine-readable states.
- `main.tex:1605-1627` reports the same states and their evidence boundary.
- Every listed path for the two `workspace_artifact` rows was verified present.
  The NVFP4 reproducer hash is
  `cc14c3dd60fb3bf1119c2b0ba0d4ab4bfe5332671432d83b3f913af6595ec3bf`;
  path/hash verification does not independently establish the candidate claim.

This is “done” only for clear reporting. Operationally, duplicate checks are
partial for four rows and absent for one; three nightly/promotion states remain
pending. None may be silently treated as promoted.

### R7 - Generation errors: partial

Evidence:

- Benchmark notebook cell 7 labels syntax, AST-policy, timeout, runtime,
  wrong-API, no-oracle, and fake-assertion outcomes.
- `generation_error_analysis/validation_output/failure_summary.json` classifies
  all 480 immutable rows by baseline/group/seed with tri-state
  denominators. Overall it finds syntax=173/480, wrong/missing target=6/307
  known, missing import=0/307, shape/dtype=7/307, missing oracle=240/307,
  fake assertion=2/307, and truncation=230/480.
- `analysis_manifest.json` hashes the input, records 20 categories, separates
  smoke from campaign rates, and verifies no missing task IDs, duplicate
  task-baseline rows, or unexpected baselines.
- `main.tex:669-674` defines wrong API, missing import, syntax, shape/dtype,
  setup, timeout, no oracle, and fake assertion; `main.tex:704-721` provides
  limited one-seed 40-API target/runtime counts.

Gap: four seeds are absent. The post-labeler's missing-import and
shape/dtype categories still need the planned manual review sample/agreement
audit before detector-accuracy claims; then aggregate the complete campaign.

### R8 - Numerical oracle: partial

Evidence:

- `main.tex:982-1033` reports 29/30 injected defects certified versus 28/30
  at fixed `1e-4`, with 0/20 clean false positives. This is a paper
  transcription: the underlying fault-injection result file was not located.
- `main.tex:1035-1060`: separate Ampere/T4 runs mention compiled, layout,
  split-k, CPU, and T4 compiled-fusion paths.
- `EXPERIMENT_PROTOCOL.md:89-91` specifies the missing complete factorial.
- `main.tex:1782,1794` still lists rerun/stronger-oracle work.
- `experiments/numerical_oracle/evidence_matrix.json` audits every
  device/mode/check/dtype cell and separates source, validation-only,
  paper-only, and missing evidence.
- `validation_output/summary.local.json` verifies the runnable protocol on one
  local CPU/eager seed: forward/gradient, float32/float64, clean/injected,
  absolute/relative/ULP, and fixed `1e-3`/`1e-4`/`1e-5`. It explicitly sets
  `all_factorial_dimensions_present=false`, `certified_bound_present=false`,
  and `ready_for_paper_result=false`.
- `validation_output/summary.local_cpu_eager_compiled.json` verifies the same
  protocol with CPU eager and CPU compiled requested together: eager cells are
  measured, while compiled cells are explicitly recorded as unsupported on the
  current Windows/PyTorch host.
- `blackwell_nvfp4_fuzz/results/nvfp4-final-validation-20260630-report.md`
  is source evidence for domain-specific Blackwell CUDA forward/property and
  compiled work, not for the requested matched factorial.

Gap: no underlying certificate/fault-injection result artifact and no matched
campaign CPU/CUDA x eager/compiled x forward/gradient table. The current
Windows/PyTorch host records CPU compiled cells as unsupported, so measured
compiled coverage still requires Linux/Colab/container execution. Gradient,
ULP, and all three fixed thresholds currently exist only in one-seed local
validation; campaign certified-bound and float32/float64 breakdowns remain
missing.

### R9 - Atlas effectiveness: partial

Evidence:

- `experiments/atlas_intervention/collect_atlas_intervention.py` implements two
  separate paired interventions: identical-summary duplicate triage and
  regenerated Atlas-guided planning. It holds model, decoding, seed, harness,
  and base input constant, records counterbalanced arm order, and verifies the
  raw Atlas file against a separate manifest before opening the paper gate.
- `experiments/atlas_intervention/test_atlas_intervention.py` passes 16/16
  contract tests, including tampered-source rejection, pair-confound detection,
  unknown-verification handling, schema validation, and source-absent fail
  closure.
- `validation_output/validation_manifest.json` hashes the executable bundle and
  records `evidence_label=validation_only`,
  `summary_ready_for_paper_result=false`, and
  `effectiveness_claim_allowed=false`.
- `experiments/vn_funnel/atlas_snapshot.json` still records
  `measured_duplicate_candidates=null`,
  `measured_atlas_guided_candidates=null`, and
  `retrieval_intervention_logged=false`; its raw dataset and independent
  manifest are absent.
- `main.tex:1629,1725` correctly treats 7,275 records/2,653 clusters as a
  paper-reported resource, not an effectiveness result.

Gap: recover/freeze a real Atlas source, execute duplicate-triage pairs on real
candidate summaries, and separately regenerate planning pairs. Only then report
matched/rejected duplicates, guided candidates, unique reproduced candidates
per 1,000, and triage time. The four synthetic fixture events are arithmetic
tests and must never be used as the effectiveness denominator.

### R10 - Reproducibility, runtime, artifact: partial

Evidence:

- Benchmark cells 6/7/9/10/11 pin model revisions/hashes and record runtime,
  package/GPU metadata, decoding, seeds, run signature, event time, and JSONL.
- The campaign checkpoint preserves the raw-stream/run-manifest/executed-
  notebook hashes, frozen code/configuration contracts, coverage, event-wall
  runtime, campaign span, throughput, and explicit readiness blockers.
- The output notebook records Tesla T4 setup and a 480/480 runtime transcript;
  `audit_checkpoint_provenance.py` hashes that notebook, the manifest, frozen
  code, and persisted JSONL and confirms all 480 raw rows are available.
- `main.tex:1037-1055,1632-1675,1719-1727` reports selected archived
  throughput/environments and says no public URL/DOI exists.
- `EXPERIMENT_PROTOCOL.md:109-111` gives the complete release checklist.
- `experiments/reproducibility/artifact_manifest.schema.json` and
  `collect_artifact_manifest.py` define a fail-closed environment/run/artifact
  contract with SHA-256s, one-signature checking, timing, throughput, resource
  fields, and explicit pending values.
- `validation_output/artifact_manifest.local.json` verifies the collector host
  and frozen 120-API manifest without claiming campaign runtime evidence.
- `validation_output/artifact_manifest.smoke.json` aggregates the real
  four-event smoke stream but explicitly records
  `full_benchmark_complete=false` and `ready_for_release=false`.

Gap: the collector exists, but the complete 2,400-event run still must be
persisted. Add the environment lock/container digest, campaign driver, total
GPU/CPU hours, and a sanitized hashed release with stable URL/DOI.

## Dependency-aware next run order

1. **Finish the 2,400-event frozen benchmark first.** This unlocks R1-R5, R7,
   and R10. Preserve each seed shard's signature, immutable raw stream, and the
   cross-shard configuration-equivalence proof.
2. **Freeze and aggregate the corpus.** Produce per-baseline/group/error tables
   and paired B2/B3 statistics before changing prompts or models.
3. **Import and replay.** Feed the same events to the Vn normalizer and component
   ablation; leave unavailable triage fields pending.
4. **Run the numerical factorial in parallel.** It is independent of completion
   generation: CPU/CUDA, eager/compiled, forward/gradient, float32/float64,
   and fixed `1e-3`/`1e-4`/`1e-5` thresholds.
5. **Triage actual anomalies.** Reproduce, minimize, duplicate-check, test stable
   and nightly/main, then decide promotion.
6. **Evaluate Atlas.** Duplicate triage can replay frozen summaries; planning
   changes generation and must be a separate enabled/disabled generation run.
7. **Package last.** Build the lock/container, commands, resource accounting,
   hashes, and public artifact only after upstream results stop changing.

The JSON file is the canonical machine-readable matrix; this Markdown file is
the human-readable rendering.
