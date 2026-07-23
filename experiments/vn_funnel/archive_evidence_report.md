# Archived Vn Gate and DL-Issue Atlas evidence

> Missing evidence is reported as missing, never as zero. Counts from different campaign denominators are not pooled.

## Funnel evidence coverage

| Stage | Campaigns with a logged value | Campaigns missing the value |
|---|---:|---:|
| `raw` | 4 | 1 |
| `parseable` | 0 | 5 |
| `ast_pass` | 0 | 5 |
| `runnable` | 4 | 1 |
| `target_valid` | 0 | 5 |
| `oracle_bearing` | 1 | 4 |
| `reproducible` | 2 | 3 |
| `non_duplicate` | 0 | 5 |
| `minimized` | 0 | 5 |
| `stable_nightly` | 0 | 5 |
| `promoted` | 0 | 5 |

## Candidate ledger

The structured ledger contains 5 candidate-family rows. Recorded completed Vn promotions: **0**.

Duplicate-check states: `{"no": 1, "partial": 4}`.
Promotion states: `{"no": 2, "pending": 3}`.

## DL-Issue Atlas

The paper-reported snapshot has 7,275 normalized records, 5,868 unique issues, and 2,653 canonical clusters.
This is 2.74 records and 2.21 unique issues per canonical cluster on average.
PyTorch contributes 72.6% of records and TensorFlow 27.4%.

The archive does **not** contain an enabled-vs-disabled retrieval intervention, so duplicate candidates detected by Atlas and Atlas-guided candidates remain `null` rather than zero.
The raw Atlas dataset/manifest is also absent from this workspace. The counts are arithmetically consistent (5,285 + 1,990 = 7,275) but not independently recomputed; the audit status is `internally_consistent_not_independently_recomputed`.

## Unsupported aggregate claims

- An aggregate archived raw-to-promoted conversion rate.
- The number of candidates de-duplicated by the Atlas.
- The number of generations planned or redirected by the Atlas.
- Independent recomputation of Atlas corpus counts from a raw local artifact.
