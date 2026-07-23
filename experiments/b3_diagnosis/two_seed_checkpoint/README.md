# B3 two-seed independent diagnosis

This directory records the independent CPU/static audit of the 240 B3 events
and their 240 same-prompt B2 controls.

- Received package SHA-256:
  `bd2c761005628d247430c1d059757d2fe88317dbb4011464d66ab198d5128ef1`
- Package validator on the local copy: PASS (240 B3 events, 240 complete
  pairs, zero prompt mismatches, and unchanged evidence hashes).
- Claim boundary: the audit directly supports max-token exhaustion and a
  repetitive multi-turn output phenotype. Chat-template/stop/EOS mismatch is
  plausible but unverified. It does not establish weight, training, merge,
  conversion, or quantization failure.

The tracked files are the review, deterministic diagnostic JSON/CSV, analyzer,
proposed new-signature runner patch, and one-hour micro-rerun plan. Immutable
benchmark JSONL remains in `benchmark_results/two_seed_checkpoint/` and is not
duplicated here.

The received external unit suite reported eight passing tests. On the local
Python 3.11 environment, one auxiliary unclosed-bracket heuristic recomputed 63
instead of the package's expected 64. That version-sensitive count is not used
in the paper; all paper-used marker, repetition, pairing, and outcome counts are
present in `b3_diagnostics.json` and independently cross-checked against the
review.
