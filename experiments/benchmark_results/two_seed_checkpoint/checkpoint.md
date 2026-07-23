# Frozen benchmark checkpoint

- Evidence label: `campaign`
- Event stream SHA-256: `03bbd2b8d20901e521ab7bfbc3a4816a770c657c65ac32c79d058af159de5a8d`
- Observed / expected events: **960 / 2400**
- Full benchmark complete: **false**
- Ready for paper result: **false**
- Blockers: `expected_events_missing`, `b2_b3_pairs_incomplete`, `campaign_seed_shards_missing`

## Baseline coverage and outcomes

| Baseline | Observed | Parseable | AST pass | Runnable | Target valid | Oracle bearing |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 240 / 600 | 240 | 240 | 240 | 240 | 0 |
| B1 | 240 / 600 | 240 | 240 | 217 | 146 | 1 |
| B2 | 240 / 600 | 140 | 140 | 134 | 95 | 88 |
| B3 | 240 / 600 | 5 | 5 | 4 | 1 | 0 |

## Seed completion

| Seed | Observed | Expected | Complete |
|---:|---:|---:|:---:|
| 3407 | 480 | 480 | true |
| 7711 | 480 | 480 | true |
| 12011 | 0 | 480 | false |
| 19001 | 0 | 480 | false |
| 27103 | 0 | 480 | false |

## Fairness and throughput

- Complete B2/B3 pairs: 240 / 600
- B2/B3 prompt-hash mismatches among complete pairs: 0
- Contract-eligible paired comparisons: 240
- Frozen logical Latin schedule balanced: true
- Full physical A/B order balance verified: false
- Event-wall throughput: 295.98533462141273
- Campaign-span throughput (includes idle/restart gaps): 18.092885265874468

Partial rows and rates are checkpoint evidence only. They must not be described as a completed campaign.
