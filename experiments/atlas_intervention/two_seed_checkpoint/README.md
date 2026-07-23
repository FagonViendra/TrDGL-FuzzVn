# Atlas status for the two-seed checkpoint

The Vn triage retained one provisional `torch.compile` signal, but the raw
DL-Issue Atlas export and its independent collection manifest are absent from
the shared workspace. Therefore neither the duplicate-triage intervention nor
the guided-planning intervention can be executed as a verified enabled/disabled
pair.

`atlas_blocker_manifest.json` deliberately records `null` for duplicate
detections, duplicate rejections, retrieval precision, Atlas-guided candidates,
and paired effects. A null value means unavailable evidence; it is not a
measured zero. The paper-reported 7,275 records and 2,653 clusters remain an
internally consistent snapshot description only.

Run the compact verifier from the workspace root:

```powershell
python TrDGL-FuzzVn_paper/experiments/atlas_intervention/verify_two_seed_atlas_checkpoint.py
```

The Atlas effectiveness requirement remains open until the original export is
recovered, frozen with `freeze_atlas_source.py`, and used in counterbalanced
paired interventions across all declared seeds.
