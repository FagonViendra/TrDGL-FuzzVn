# Paper integration guide

The audit-safe blocks are integrated in `main.tex` as Tables `tab:vn_field_coverage` and `tab:candidate_ledger_en`, plus the Section 5.3 artifact paragraph. This file records how to refresh or transplant them without changing their interpretation.

The generated file `paper_snippets.tex` contains three independently insertable blocks. Do not `\input` the whole file in one place.

- Section 4.5: replace or follow the archived-campaign table with `tab:vn_field_coverage`. It reports **logging coverage**, not conversion rates. Keep the paragraph stating that campaign units differ and cannot be pooled.
- Section 4.7: replace the narrative two-column candidate table with `tab:candidate_ledger_structured`. Candidate details remain in `candidate_ledger.jsonl`/`.csv`; the paper table exposes the six verification decisions consistently.
- Section 5.3: add the artifact paragraph after the rerun command/environment description. It states exactly which artifacts are executable and records the Atlas-source limitation.

Run `python build_archive_report.py` before compiling the paper. If the raw Atlas corpus is later recovered, add its path, content hash, collection query/date, and recomputed counters to `atlas_snapshot.json`; only then change the audit status or replace `null` intervention outcomes.
