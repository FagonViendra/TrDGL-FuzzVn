# TrDGL-FuzzVn submission gap checklist

Last synchronized with `experiments/evidence_audit/requirements_matrix.json` on
2026-07-10. A checked item means the reporting/artifact contract is present; it
does not convert validation-only data into a campaign result.

## Ready in the manuscript

- [x] Five-section structure requested by the supervisor.
- [x] Four internal baselines B0--B3 are defined under one frozen harness.
- [x] The 120-API/10-group/five-seed protocol and 2,400-event denominator are explicit.
- [x] The ordered 11-stage Vn funnel uses tri-state missingness rather than coercing null to zero.
- [x] Candidate status is centralized in the JSONL/CSV ledger.
- [x] Diagnostic ablation, Atlas, numerical-oracle, and reproducibility artifacts are labeled as non-final results.
- [x] The two complete shards for seeds 3407 and 7711 (960/2,400 events; B0--B3=240 each) are reported only as a two-seed diagnostic checkpoint, not as the completed five-seed campaign.
- [x] The real two-seed Vn funnel reports 960 raw, 625 parseable/AST-pass, 595 runnable, 482 target-valid, and 89 oracle-bearing events; all downstream full-denominator states remain unknown.
- [x] The real two-seed B3 ablation replays 240 identical programs across full/no-AST/no-oracle/no-Vn/no-Atlas conditions and keeps unavailable Vn/Atlas effects null.
- [x] Paper-only numerical fault-injection values are identified as lacking a source result file.
- [x] The candidate reporting requirement (R6) is complete, while unfinished verification states remain visible.
- [x] Long Blackwell/training engineering material is rendered under Section 4.8; Section 4.4 now stays focused on numerical oracles and base-versus-tuned evidence.
- [x] Reproducibility completeness is based on unique `(baseline, task_id)` identities with duplicate/missing-identity and B0--B3 balance checks.
- [x] Numerical-oracle event IDs bind the complete experimental design, and certified bounds require a hashed source artifact.
- [x] The five-seed local numerical design records all 480 cells: 240 CPU/CUDA eager cells measured and 240 CPU/CUDA compiled cells unsupported on the current Windows/PyTorch host.
- [x] Numerical fixed-threshold controls report 0/120 clean false positives and injected-delta detections of 40/40 at `1e-5`, 40/40 at `1e-4`, and 0/40 at `1e-3`.

## Blocking empirical work

- [ ] R1/R2: complete 600 events for each B0--B3 baseline (2,400 total) under one compatible protocol.
- [ ] R3: obtain all 600 same-prompt B2/B3 pairs with no prompt/harness mismatch and report paired uncertainty.
- [ ] R2: rerun one external comparator on a declared compatible subset, or document a concrete incompatibility.
- [ ] R4: extend the checked two-seed replay to all five shards; populate post-oracle states; run a separate Atlas planning intervention.
- [ ] R5: append reproducibility, duplicate, minimization, stable/nightly, and promotion states to real candidates so all eleven funnel stages share a denominator.
- [ ] R6 operational follow-up: complete partial duplicate checks, three pending nightly/main checks, and final promotion decisions.
- [ ] R7: extend the two-seed 960-event error tables to the complete stream and complete the two-reviewer manual audit sample.
- [ ] R8: rerun the matched numerical matrix on a compiled-capable Linux environment; retain the measured CPU/CUDA eager cells and add certified bounds only where a hashed theorem/certificate justifies them.
- [ ] R8: recover and hash the source artifact behind the paper-transcribed 29/30 fault-injection figure, or rerun and replace the table.
- [ ] R9: recover/freeze the real Atlas source and independent manifest; run paired duplicate-triage and separate planning interventions on real data.
- [ ] R10: add an environment lock/container digest, total CPU/GPU hours, and a stable artifact URL/DOI; driver, commands, event timing, and throughput are already recorded for the current checkpoints.

## Blocking manuscript cleanup

- [x] Resolve the pre-existing overfull boxes; the current build reports none.

## Paper refresh gate

Before replacing any checkpoint table with final results:

1. Verify the evidence label is `campaign`, not `validation_only` or `campaign_checkpoint`.
2. Verify expected counts, run signature, manifest hash, B2/B3 prompt hashes, and order balance.
3. Regenerate benchmark, generation-error, ablation, funnel, Atlas, numerical-oracle, and reproducibility summaries from immutable inputs using their compact verifiers.
4. Update the abstract only after the corresponding source table and machine-readable result are both present.
5. Compile twice and inspect undefined references, overfull boxes, and page layout.

## Latest verification

- `pdflatex` completed twice after the Section 4.4/4.8 reorganization: 60 pages, no undefined references or citations; the subsequent layout pass reports zero overfull boxes.
- Pages spanning the 4.4 A/B transition, 4.7/4.8 boundary, and first 4.8 engineering subsections were rendered to PNG and visually checked for clipping, overlap, and legibility.
- The checkpoint diagnostics and protocol-guardrail prose now describe two complete shards and the 960-event combined stream; rerender after the next manuscript build before submission.
- The owned release contracts pass 19 focused tests: numerical oracle (9) and reproducibility (10).
- The checkpoint refresh passes benchmark-result tests 19/19, generation-error tests 52/52, and evidence-audit tests 3/3.
- `pdflatex` completed twice for the checkpoint-480 manuscript: 60 pages, no undefined references/citations, and no overfull boxes.
- The evidence-audit hash validator passes against 22 refreshed artifact hashes at paper commit `43b53190`.
