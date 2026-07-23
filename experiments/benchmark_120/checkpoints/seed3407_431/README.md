# Seed 3407 checkpoint (431/480)

This immutable recovery point contains all 120 B0, 120 B1, and 120 B2 events
for seed 3407, plus 71 persisted B3 row-level events recovered from the local
watcher backup after Colab session `trdgl-seed3407-r7` was pruned.

Only `events.checkpoint.jsonl` is counted as raw evidence. The r7 stdout log
printed a few later B3 lines, but those rows were not downloaded as JSONL before
the runtime disappeared, so they are deliberately excluded from this checkpoint.

Resume from this directory by uploading `events.checkpoint.jsonl` to
`/content/trdgl_benchmark_seed_3407/events.jsonl` and rerunning the same
notebook with `TRDGL_SEED_INDEX=0`, `TRDGL_TASK_LIMIT=0`, and
`TRDGL_OUTPUT_DIR=/content/trdgl_benchmark_seed_3407`.

B3 remains incomplete: 49 of 120 B3 events are still missing. No final
four-baseline comparison is permitted until a validated 480/480 checkpoint is
frozen.
