TrDGL-FuzzVn full reproducibility artifact
Created: 2026-07-24 00:08:36 +07:00
Source root: C:\Users\fagon\OneDrive\Documents\New project 2\TrDGL-FuzzVn_paper
Included: paper source/PDF, 39 Python scripts, 6 notebooks, Markdown protocols, JSON/JSONL/CSV evidence, schemas, figures, and logs.
Excluded: __pycache__, *.pyc, and the obsolete nested report.zip duplicate.
License: original project software requires compliance with both PolyForm Noncommercial 1.0.0 and Parity 7.0.0; third-party materials remain under their own terms.
Validation: all 39 Python files pass py_compile. 10 of 11 test scripts pass; experiments/evidence_audit/test_refresh_stable_hashes.py has 1 assertion failure because immutable_campaign_checkpoint_events disagrees with the observed machine-readable campaign count.
Important: no dependency lockfile/container digest is present; raw DL-Issue Atlas corpus remains absent; only two generation seeds are complete.
