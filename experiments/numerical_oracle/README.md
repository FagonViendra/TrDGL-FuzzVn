# Matched numerical-oracle protocol

This directory supplies the reproducible contract for Section 4.4. It does not
turn local validation into a campaign result.

## Files

- `run_numerical_oracle_protocol.py`: emits one JSONL event for every declared
  device, mode, check, dtype, control, threshold, and seed cell.
- `collect_numerical_oracle_results.py`: validates event identity and evidence
  semantics, then creates a coverage/result summary without imputing cells.
- `numerical_oracle_event.schema.json`: strict event schema.
- `evidence_matrix.md`: audit of located, paper-only, missing, and runnable evidence.
- `validation_output/`: earlier one-seed CPU validation streams.
- `five_seed_local_checkpoint/`: current 480-event local diagnostic. It measures
  CPU/CUDA eager cells and records CPU/CUDA compiled cells as unsupported.
- `package_five_seed_local_checkpoint.py` and
  `verify_five_seed_local_checkpoint.py`: create and verify the compact evidence
  bundle without re-running the matrix.

## Fail-closed rules

- Event IDs hash the complete experimental design, including run ID, backend,
  injected delta, tolerance, and certified-bound source hash.
- A certified bound requires a real source artifact; its SHA-256 is recorded in
  every certified event.
- `unsupported`, `error`, and `pending` cells do not count as measured factorial coverage.
- Non-finite or negative error/timing values are rejected.
- One run ID cannot silently mix different environment records.
- `ready_for_paper_result=true` requires campaign labeling and every one of the
  five seeds x CPU/CUDA x eager/compiled x forward/gradient x float32/float64 x
  three fixed-threshold cells measured, plus certified evidence and no
  unresolved statuses.

The full campaign command is documented in `evidence_matrix.md`. Run tests from
the paper root with:

```powershell
python -m unittest discover -s experiments/numerical_oracle -p "test_*.py" -v
```

For the current checkpoint, the compact no-rerun check is:

```powershell
python experiments/numerical_oracle/verify_five_seed_local_checkpoint.py
```

It prints one JSON PASS line. A `null` compiled effect and
`ready_for_paper_result=false` are required outcomes while compiled execution
and a sourced certified bound remain unavailable.
