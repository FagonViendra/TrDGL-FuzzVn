# TrDGL-FuzzVn

Repository for the experiment code, notebooks, protocols, and machine-readable
evidence. PDF, TeX, and local report-build artifacts are intentionally excluded
from Git tracking.

- `EXPERIMENT_PROTOCOL.md`: frozen protocol and evidence-status checklist for the additional controlled experiments.
- `experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb`: self-contained Colab notebook with the frozen 120-API/10-group/5-seed manifest and resumable four-baseline runner.
- `experiments/b3_diagnosis/three_seed_stopfix_20260724/`: verified B3-only
  continuation for seeds 12011, 19001, and 27103, including a separate
  provenance note.

## B3 continuation boundary

- The 360 B3 tasks reuse the frozen benchmark task IDs, documentation snapshot,
  and exact full-prompt hashes used by B2. They do not consume generated B1 or
  B2 programs as inputs.
- The tuned Q3_K_M model file and decoding settings match the original B3
  checkpoint.
- The continuation uses the Snowflake workflow on an NVIDIA RTX PRO 6000
  Blackwell instead of the Colab T4 path to reduce generation time.
- This is not a hardware-only replication: the serving wrapper also adds string
  stops and marker-fragment cleanup, and execution evaluation is a separate CPU
  step. B0, B1, and B2 rows remain absent for the three continuation seeds.

## License

Copyright (c) 2026 TrDGiL.

Original project software is source-available under the combined terms of
[PolyForm Noncommercial 1.0.0 and Parity 7.0.0](LICENSE). Both licenses apply
concurrently:

- use is limited to noncommercial purposes;
- software developed, operated, or analyzed with this software must have its
  source code published as required by Parity 7.0.0, subject to its narrow
  prototype exception;
- commercial use requires a separate written license from TrDGiL.

Because commercial use is restricted, this is not an OSI-approved open-source
grant. Third-party templates, models, datasets, generated model outputs, and
other bundled materials remain subject to their respective licenses and
notices.
