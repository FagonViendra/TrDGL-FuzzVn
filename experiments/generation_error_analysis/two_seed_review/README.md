# Two-seed detector-review sample

`review_sample.csv` is a deterministic, stratified 24-record sample from the
960-event combined checkpoint (source SHA-256
`03bbd2b8d20901e521ab7bfbc3a4816a770c657c65ac32c79d058af159de5a8d`).
The selection covers positive automatic labels, rare categories, known
analyzer/harness disagreements, and a no-detected-failure fallback while
deduplicating records.

The current status in `review_sample_manifest.json` is
`awaiting_two_independent_reviewers`. No reviewer fields have been filled. To
complete validation, two distinct reviewers must independently copy the CSV,
fill every `review_*` field with `true`, `false`, or `unknown`, and then run the
agreement command documented in the parent `README.md`. Until then, this folder
is review infrastructure rather than detector-accuracy evidence.
