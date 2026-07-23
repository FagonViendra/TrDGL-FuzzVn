# Changelog

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

Full engineering details remain in `../main.tex`.

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

## 6. Delivered Files

Contents of `teacher_report_20260711/`:

| File | Role |
|---|---|
| `fuzz-report.pdf` | **Main report** (~10 pages) |
| `CHANGELOG_TEACHER_20260711.md` | Diff: previous draft → current (this file) |
| `fuzz-report.tex` + `fuzz-refs.bib` | Source for recompilation |
| `figs/atlas/*.pdf` | Atlas figures (paper snapshot) |

Rebuild command (PowerShell, from this directory):

```powershell
pdflatex -interaction=nonstopmode -halt-on-error fuzz-report.tex
bibtex fuzz-report
pdflatex -interaction=nonstopmode -halt-on-error fuzz-report.tex
pdflatex -interaction=nonstopmode -halt-on-error fuzz-report.tex
```

Suggested filenames for submission:

- `TrDGL-FuzzVn_teacher_report_20260711.pdf`
- `CHANGELOG_TEACHER_20260711.md`

---

## 7. Next Steps (listed in PDF, not yet completed)

1. Micro-rerun B3 (1 hour), crossed order + stop/template telemetry
2. Replay candidate in pinned T4/PyTorch environment
3. Numerical matrix on Linux host with compiler support
4. Recover/rebuild Atlas corpus
5. Artifact publication (alias path, lock/container, DOI/URL)
