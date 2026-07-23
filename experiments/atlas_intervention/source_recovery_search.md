# DL-Issue Atlas source-recovery search

Search date: 2026-07-08. Scope: the shared workspace rooted at
`C:/Users/fagon/OneDrive/Documents/New project 2`; no claim is made about
unmounted drives, cloud storage, deleted files, or external repositories.

Two read-only searches were run from the workspace root:

```powershell
rg --files -g '*atlas*' -g '*Atlas*' -g '*issue*' -g '*Issue*'
rg -n -i "7,?275|2,?653|DL-Issue|Issue Atlas" TrDGL-FuzzVn_paper tmp reports
```

The filename search found only the intervention tooling, the derived
`vn_funnel/atlas_snapshot.json`, and unrelated image-texture atlases. The
content search found paper/PDF transcriptions and derived audit reports of the
7,275-record/2,653-cluster snapshot. It did not find a raw PyTorch/TensorFlow
issue export or an independent collection manifest.

Accordingly, `measured_duplicate_candidates` and
`measured_atlas_guided_candidates` remain null, and the Atlas collector remains
`ready_for_paper_result=false`. Recovery must use the original archive/export
location; the reported corpus counts cannot be reverse-engineered into raw
records or treated as an effectiveness experiment.

## Follow-up search on 2026-07-10

A second workspace-wide filename scan after the two-seed checkpoint found four
Atlas/issue data-like names: the derived `vn_funnel/atlas_snapshot.json` and
three Atlas JSON schemas. It found no `.json`, `.jsonl`, `.csv`, or `.parquet`
raw issue export and no independent source manifest. A targeted content search
under `TrDGL-FuzzVn_paper`, `tmp`, and `reports` also found no new raw corpus.

The new provisional `torch.compile` signal therefore cannot be submitted to an
Atlas enabled/disabled retrieval pair. Its Atlas duplicate decision,
Atlas-guidance status, retrieval precision, and intervention effect remain
`null`; this is an evidence blocker, not a measured zero.
