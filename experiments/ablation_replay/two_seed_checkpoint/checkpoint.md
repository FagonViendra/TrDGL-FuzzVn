# Two-seed ablation diagnostic checkpoint

This bundle replays immutable B3 programs from complete seed shards 3407 and 7711. It covers 240/600 planned B3 programs (2/5 seeds) and is not a final paper result.

## Measured boundary

- Full B3 funnel: 240 raw -> 5 parseable/AST-pass -> 1 target-valid -> 0 oracle-bearing.
- Removing the ablatable AST quality policy changes AST-pass by 0; this is descriptive, not conclusive.
- Removing the oracle gate admits 1 additional program, but 1 downstream decision remains pending.
- Vn and Atlas effects are unavailable, not zero: neither gate has an eligible B3 input at this checkpoint.

## Paired base-versus-tuned diagnostic

All 240 B2/B3 pairs share the same prompt hash. B2 versus B3 target-valid counts are 95/240 versus 1/240; oracle-bearing counts are 88/240 versus 0/240. This checkpoint does not support a tuning-improvement claim.

## Claim boundary

Complete two-seed ablation diagnostic checkpoint only. It reports observed gate pass-through counts and unavailable effects; it is not the planned five-seed ablation and not evidence of confirmed bug yield.
