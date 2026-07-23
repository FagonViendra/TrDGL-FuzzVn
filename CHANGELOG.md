# Changelog

## 2026-07-24 03:15 GMT+7 — B3 serving repair and remaining-seed extension

### Added

- Added the verified 17-file Snowflake evidence bundle at
  `experiments/b3_diagnosis/three_seed_stopfix_20260724/`.
- Added B3 Q3_K_M generation and CPU evaluation for seeds `12011`, `19001`,
  and `27103` (120 APIs per seed).
- Added the frozen 360-task prompt stream, generation contract, Q3/Q4
  stop-fix probes, manifests, summaries, and execution notebooks.
- Added a provenance note that distinguishes prompt reuse from output reuse and
  records the environment change.
- Updated the local reports to distinguish the balanced two-seed checkpoint
  from the repaired-contract B3-only extension.
- PDF, TeX, and local report-build artifacts are excluded from Git tracking.
- Repository history was rewritten to remove previously committed PDF, TeX,
  BibTeX, and report-build artifacts; local copies remain outside Git.

### Recorded results

| Stream | Result |
|---|---:|
| B3 Q3_K_M generation | 360/360 |
| Finish reason | 334 stop; 26 length |
| Marker leakage | 0/360 |
| Generated tokens / time | 90,698 / 679.1 s |
| Mean generation throughput | 133.5 tokens/s |
| CPU evaluator exit zero | 255/360 (70.8%) |
| Exit zero by seed | 85/120; 86/120; 84/120 |
| Q3 stop-fix probe | clean output 0/4 → 4/4 |
| Q4 stop-fix probe | clean output 0/4 → 4/4 |

The telemetry identifies a serving-contract mismatch: the literal
`<end_of_turn>` marker is not atomic in either pinned GGUF vocabulary, while
the original runtime stops only on an EOG token. The repaired wrapper adds
string stops and strips complete or orphaned marker fragments.

### Evidence boundary

- The continuation reuses the frozen task IDs, documentation snapshot, and
  exact B2 full-prompt hashes for all 120 APIs. It does not use generated B1 or
  B2 programs as inputs.
- The tuned Q3_K_M model SHA-256 and decoding settings are unchanged from the
  original B3 checkpoint.
- Generation moved from the Colab T4 path to the Snowflake workflow on an
  NVIDIA RTX PRO 6000 Blackwell to reduce runtime.
- The continuation is not a GPU-only replication because the serving wrapper
  also changes stop handling and marker cleanup; evaluation is a separate CPU
  subprocess stage.
- The original two-seed B0–B3 checkpoint remains unchanged at 960/2,400
  balanced events.
- The 360 new rows are B3-only and use a repaired serving contract; they are
  not pooled with the original B2/B3 comparison.
- B0/B1/B2 are still missing for seeds `12011`, `19001`, and `27103`.
- `exit zero` is a CPU subprocess verdict, not automatically a
  target-valid, oracle-bearing, novel, or confirmed-bug verdict.
- Q4 is sensitivity/repair evidence and is not part of the Q3 campaign
  denominator.

### Integrity and operational notes

- `b3_results.jsonl`: 360 rows,
  SHA-256 `8546fe7fb7e4f6c9cec06641483e3eef79bbbeec3c4bac282ff8965bdc6ecc5e`.
- `b3_eval_results.jsonl`: 360 rows,
  SHA-256 `0ccec046d6bebd8f21c4834c307fe85d3ed93bcd6dd5303cedc56fe371dadd99`.
- All files named by the four nested manifests were independently checked for
  existence, byte size, and SHA-256.
- Source ZIP: 382,877 bytes, 17 entries, SHA-256
  `F7E9C80E63EE0F1E6B2198A0507B84EE206BCD0740857017C0A52AEBA411AB9C`.
- The initial local downloader lacked `snowflake.snowpark`; SQL `GET` via
  Snowflake Connector was used instead. The first manifest parser also assumed
  a list instead of the observed `{"artifacts": {...}}` structure. Both issues
  were corrected before the final verification.
- Connector dependency warnings did not affect the verified download. No raw
  console log was present on the stage. No credential value is stored in the
  committed notebooks; any Snowflake password previously disclosed outside
  this repository should still be rotated.

---

## 2026-07-11 — Two-seed evidence lock

---

## 1. Summary

| Item | Previous (06/2026) | Current (11/07/2026) |
|---|---|---|
| PDF length | ~14 pages (loose layout) | **~10 pages**, compact layout |
| Seed generation | 5-seed plan, 2 shards partial | **2 seeds complete** (3407 & 7711, 960 events) |
| Fine-tuning claim | Implied improvement | **No claim**; B3 regression documented |
| Placeholders / gaps | Some ambiguous or paper-transcribed numbers | Gaps marked as **unknown / pending / future work** |
| Deliverables | PDF draft only | PDF + this changelog |

---

## 2. New Content

### 2.1. Locked Evidence (with artifacts)

- Benchmark expanded to **120 PyTorch APIs / 10 groups**.
- Four baselines **B0–B3** in the same harness:
  - B0 random/template, B1 base/minimal, B2 base/full, B3 tuned/full.
- **Two complete seeds** `3407` and `7711`:
  - 960 total events; 240 per baseline.
  - 240 paired B2/B3 runs on **identical prompts** (prompt-hash mismatch = 0).
- Two-seed checkpoint results:
  - **B2**: 140 parseable, 95 target-valid, 88 oracle-bearing.
  - **B3**: 5 parseable, 1 target-valid, 0 oracle-bearing.
- Error taxonomy over **960 events** (true / known / unknown).
- **Vn funnel**: raw → parseable → runnable → target-valid → oracle-bearing;
  post-oracle stages (reproduce, de-dup, minimize, stable/nightly, promote)
  marked **unknown** where evidence is not yet collected.
- Ablation on **same corpus** for AST, oracle, Vn, Atlas, fine-tuning;
  null where eligibility is insufficient (especially B3).
- Numerical diagnostic: **480 design cells**; 240 eager measured;
  240 compiled unsupported on Windows host; clean FP = **0/120**.
- Candidate ledger: **1 entry**
  (`CAND-BENCH-TORCH-COMPILE-3407`), all triage fields Pending/Unknown.
- Runtime/throughput reported as **active event-wall** (excludes sleep).
- Independent B3 diagnostics:
  - 240/240 hit max-token ceiling;
  - 232/240 leaked turn-delimiter / truncated prefix;
  - Median 4-gram repetition: 0.364 (B3) vs 0.158 (B2);
  - Chat-template/stop/EOS mismatch remains an **unverified hypothesis**.

### 2.2. Paper Structure

Follows a progress-report format:

1. Introduction / motivation / contributions
2. Related work
3. Method (pipeline, baselines, Vn, Atlas, numerical)
4. Experimental setup & results (two-seed lock)
5. Threats, reproducibility, limitations, conclusion

The full report source is retained locally and excluded from Git.

---

## 3. Downgraded or Removed Claims

| Previous claim | Current treatment |
|---|---|
| 5-seed benchmark as completed | **Two-seed checkpoint only**; 3 seeds remaining |
| Fine-tuning improves generation | **No claim**; B3 regression on recorded GGUF artifact |
| Atlas "effective" / 7,275 as measured | **Paper snapshot only**; raw collection missing |
| Compiled numerical / certified bound as measured | Compiled = unsupported on local host; certified source absent |
| Candidate promoted / bug found | 0 promoted; 1 provisional, triage incomplete |
| Zero post-oracle = "novelty failed" | **Unknown ≠ fail**; evidence not yet collected |
| Five candidate ledger entries | Only 1 entry with current source retained |

---

## 4. Layout Changes

- Artifact availability table reduced to **single-column** (`\columnwidth`), placed near Reproducibility section.
- Candidate table converted to single-column key–value format.
- Conclusion/future work shortened; `\enlargethispage` applied to prevent orphan refs page.
- Minor overfull fixes (Vn enumerate, numerical design sentence, hash prefixes).
- Remaining large overfull in `\maketitle` (~123 pt) is caused by the CAS class; does not affect readability.

---

## 5. Evidence Boundaries

Items explicitly marked as incomplete in the report:

- External comparator not yet re-run for compatibility
- Three seed generations not yet executed
- Raw DL-Issue Atlas corpus not yet recovered
- Compiled numerical / certified bound
- Replay, duplicate check, minimize, stable/nightly for candidate
- Lock/container digest, resource-hour accounting, public URL/DOI

---

## 6. Local Report Artifacts

Report sources, compiled PDFs, figures used only by the report, and LaTeX build
files are retained locally and excluded from Git. The repository contains the
machine-readable evidence and this changelog.

---

## 7. Next Steps at This Checkpoint

1. Micro-rerun B3 (1 hour), crossed order + stop/template telemetry
2. Replay candidate in pinned T4/PyTorch environment
3. Numerical matrix on Linux host with compiler support
4. Recover/rebuild Atlas corpus
5. Artifact publication (alias path, lock/container, DOI/URL)
