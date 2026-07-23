# TrDGL-FuzzVn paper

Working LaTeX source for reorganizing the original English report into the five-part paper structure requested by the supervisor.

- `main.tex`: reorganized five-part manuscript.
- `teacher_report_20260711/fuzz-report.tex`: concise supervisor-facing report,
  updated through 24 July 2026.
- `output/pdf/TrDGL-FuzzVn_teacher_report_20260724.pdf`: compiled
  supervisor-facing report.
- `output/pdf/TrDGL-FuzzVn_full_report_20260724.pdf`: compiled full report.
- `EXPERIMENT_PROTOCOL.md`: frozen protocol and evidence-status checklist for the additional controlled experiments.
- `experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb`: self-contained Colab notebook with the frozen 120-API/10-group/5-seed manifest and resumable four-baseline runner.
- `experiments/b3_diagnosis/three_seed_stopfix_20260724/`: verified B3-only
  serving-repair evidence for seeds 12011, 19001, and 27103. It is not a
  substitute for the missing paired B0–B2 rows.

## Provenance

- Original source: `C:/Users/fagon/Loxi/th5/11/latex_do_an_fuzz/bao_cao_LLM_API_Fuzzing_Heterogeneous_GPUs_en.tex`
- Original compiled PDF SHA-256: `95B9A8D19FCF1893A3C08420E98632D46D8CAE93C8C1190D1255FF80E22AD1C7`
- Imported source SHA-256: `91FF6ADF5CA256586CACC07F674C4C4C707DE6B9576CAB5335720D950043CAC3`

The original files under `C:/Users/fagon/Loxi` are preserved unchanged.

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
