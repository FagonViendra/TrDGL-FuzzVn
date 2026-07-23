# Validation-only bundle

This directory is an executable contract check, not an Atlas experiment.

- `summary.validation.json` aggregates four synthetic paired events.
- `validation_manifest.json` hashes the collector, schemas, fixture, audit, and
  summary and records the contract-test result.
- `effectiveness_claim_allowed` is always `false` here.

The synthetic counts exist only to test arithmetic and must not be quoted in
the paper. A real campaign belongs in a separate directory and must provide the
raw Atlas dataset plus its independent source manifest.
