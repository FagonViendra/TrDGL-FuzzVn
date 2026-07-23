TrDGL-FuzzVn B3 results downloaded from Snowflake

Downloaded and verified locally.

Contents:
- b3_campaign_run/: 360 generation records + summary + manifest
- b3_campaign_eval/: 360 evaluator records + summary + manifest
- b3_stopfix_snowflake/: Q3/Q4 stop-fix probes
- frozen_inputs/: 360 frozen B3 tasks + generation contract
- notebook/: Snowflake execution notebook artifact
- crossed_micro_rerun/: Q3/Q4 crossed micro-rerun notebook and documentation snapshot
- LOCAL_VERIFICATION_SUMMARY.json: local row counts and SHA-256 verification

Important scope:
- These are B3 tuned-model results for seeds 12011, 19001, and 27103.
- Q4 probe results are sensitivity evidence, not part of the frozen Q3 campaign denominator.
- B0/B1/B2 for the remaining seeds are not included.
