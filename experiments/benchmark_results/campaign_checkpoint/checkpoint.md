# Frozen benchmark checkpoint

- Evidence label: `campaign`
- Event stream SHA-256: `c35316c195b2d0c257fa25ef00a6fcec1d913b790810dcd7a9d78ca4e8acc60b`
- Observed / expected events: **480 / 2400**
- Full benchmark complete: **false**
- Ready for paper result: **false**
- Blockers: `expected_events_missing`, `b2_b3_pairs_incomplete`, `campaign_seed_shards_missing`

## Baseline coverage and outcomes

| Baseline | Observed | Parseable | AST pass | Runnable | Target valid | Oracle bearing |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 120 / 600 | 120 | 120 | 120 | 120 | 0 |
| B1 | 120 / 600 | 120 | 120 | 105 | 72 | 1 |
| B2 | 120 / 600 | 65 | 65 | 64 | 48 | 43 |
| B3 | 120 / 600 | 2 | 2 | 1 | 0 | 0 |

## Seed completion

| Seed | Observed | Expected | Complete |
|---:|---:|---:|:---:|
| 3407 | 480 | 480 | true |
| 7711 | 0 | 480 | false |
| 12011 | 0 | 480 | false |
| 19001 | 0 | 480 | false |
| 27103 | 0 | 480 | false |

## Fairness and throughput

- Complete B2/B3 pairs: 120 / 600
- B2/B3 prompt-hash mismatches among complete pairs: 0
- Contract-eligible paired comparisons: 120
- Frozen logical Latin schedule balanced: true
- Full physical A/B order balance verified: false
- Event-wall throughput: 289.9985308687849
- Campaign-span throughput (includes idle/restart gaps): 15.557688550128749

Partial rows and rates are checkpoint evidence only. They must not be described as a completed campaign.
