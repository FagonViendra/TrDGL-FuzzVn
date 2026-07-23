# Seed 3407 checkpoint (360/480)

This immutable recovery point contains all 120 B0, 120 B1, and 120 B2 events
for seed 3407. B3 has no persisted row-level events in this checkpoint.

An executed-notebook transcript elsewhere in the workspace reports a completed
480-event run, but the corresponding B3 JSONL was not copied before that Colab
runtime was released. The transcript is therefore not used to upgrade this
checkpoint. B3 must be regenerated through the same notebook and appended to
this verified event ledger.

Verify `checkpoint_manifest.json` before resuming. Cross-seed aggregation must
use the campaign shard-equivalence gate rather than concatenating signatures.
