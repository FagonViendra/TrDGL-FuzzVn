# Two-seed generation-error checkpoint

This directory is generated from the immutable seed-3407 and seed-7711 event
ledgers. It classifies 960 records: 240 each for B0, B1, B2, and B3. Both source
hashes, all raw denominators, unknown counts, and analyzer/harness disagreements
are retained in `analysis_manifest.json` and the row-level outputs.

The primary human-readable artifact is `validation_report.md`. Unlike the
legacy renderer, version 20 builds its coverage, failure, truncation, length,
consistency, and LaTeX tables from the explicit `campaign_combined` view. The
underlying per-shard tables remain available for audit.

Selected diagnostic counts are:

- syntax failure: B2 100/240 and B3 235/240;
- wrong/missing target API: B1 12/240; B2 has 1 positive among 140 known and
  100 unknown because those programs do not parse;
- recorded shape/dtype runtime failure: B1 9/240;
- missing-oracle evidence: B0 240/240, B1 231/240, B2 6/140 known, and B3 5/5
  known; B2/B3 retain 100/235 unknown records respectively;
- fake assertion: B2 4/140 known;
- target only in an uninvoked function: B2 118/140 known;
- length truncation: B2 219/240 and B3 240/240.

There are zero positive missing-import findings among 625 parseable records,
but 335 unparsable records remain unknown; this must not be reported as proof
that missing imports are absent. The 113 analyzer/harness disagreement rows are
audit targets, not detector-accuracy errors or PyTorch bugs.

This is a complete two-seed shard analysis but only a 960/2,400 campaign
checkpoint. It does not support a final baseline or fine-tuning claim.
