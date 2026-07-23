#!/usr/bin/env python3
"""Fail-closed verifier with compact output for the two-seed Vn checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import vn_funnel


HERE = Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parents[2]
DEFAULT_EVENTS = HERE.parent / "benchmark_results" / "two_seed_checkpoint" / "events.combined.jsonl"
DEFAULT_DOCUMENTATION = (
    HERE.parent / "benchmark_120" / "checkpoints" / "seed7711_480" / "documentation_snapshot.json"
)
DEFAULT_CHECKPOINT = HERE / "two_seed_checkpoint"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"{path}: expected JSON object")
    return value


def verify(events: Path, documentation: Path, checkpoint: Path) -> dict[str, Any]:
    event_sha = sha256(events)
    import_manifest = load_json(checkpoint / "import_manifest.json")
    require(import_manifest.get("input_sha256") == event_sha, "import input hash mismatch")
    require(import_manifest.get("records") == 960, "import record count is not 960")
    require(import_manifest.get("baselines") == {"B0": 240, "B1": 240, "B2": 240, "B3": 240},
            "per-baseline counts are not 240 each")

    normalized = vn_funnel.load_jsonl(checkpoint / "normalized_events.jsonl")
    require(len(normalized) == 960, "normalized ledger count is not 960")
    validated = [vn_funnel.validate_normalized(row) for row in normalized]
    candidate_ids = [row["candidate_id"] for row in validated]
    require(len(candidate_ids) == len(set(candidate_ids)), "normalized candidate IDs are not unique")
    require(all(row.get("source_sha256") == event_sha for row in validated),
            "normalized source hash mismatch")

    funnel = load_json(checkpoint / "funnel_report.json")
    expected_first = {
        "raw": (960, 0, 0),
        "parseable": (625, 335, 0),
        "ast_pass": (625, 335, 0),
        "runnable": (595, 365, 0),
        "target_valid": (482, 478, 0),
        "oracle_bearing": (89, 871, 0),
    }
    by_stage = {row["stage"]: row for row in funnel.get("funnel", [])}
    for stage, counts in expected_first.items():
        row = by_stage.get(stage, {})
        require((row.get("pass"), row.get("fail"), row.get("unknown")) == counts,
                f"unexpected funnel counts at {stage}")
    for stage in ("reproducible", "non_duplicate", "minimized", "stable_nightly", "promoted"):
        row = by_stage.get(stage, {})
        require((row.get("pass"), row.get("fail"), row.get("unknown")) == (0, 0, 960),
                f"post-oracle stage {stage} is not fully unknown")

    triage_dir = checkpoint / "triage"
    triage_manifest = load_json(triage_dir / "triage_manifest.json")
    require(triage_manifest.get("tool_sha256") == sha256(HERE / "triage_assertion_signals.py"),
            "triage tool hash mismatch")
    require(triage_manifest.get("input_sha256") == event_sha, "triage input hash mismatch")
    require(triage_manifest.get("documentation_sha256") == sha256(documentation),
            "triage documentation hash mismatch")
    require(triage_manifest.get("assertion_signal_count") == 4, "assertion signal count is not 4")
    decisions = triage_manifest.get("decision_evidence", {})
    require(decisions.get("decision_counts") == {
        "pending_pinned_environment_replay": 1,
        "rejected_invalid_oracle": 3,
    }, "triage decision counts mismatch")
    require(decisions.get("anomaly_counts") == {"true": 0, "false": 3, "unknown": 1},
            "triage anomaly counts mismatch")
    require(decisions.get("promoted_count") == 0, "triage contains a promoted signal")
    decision_path = triage_dir / "triage_decisions.jsonl"
    require(decisions.get("sha256") == sha256(decision_path), "decision ledger hash mismatch")

    triage_summary = load_json(triage_dir / "triage_summary.json")
    require(triage_summary.get("benchmark_funnel") == [
        {"stage": stage, "pass": passed, "fail": failed, "unknown": unknown, "total": 960}
        for stage, (passed, failed, unknown) in expected_first.items()
    ], "triage summary funnel does not match canonical funnel")

    ledger_path = checkpoint / "candidate_ledger.jsonl"
    ledger_report = vn_funnel.validate_ledger(ledger_path)
    ledger = vn_funnel.load_jsonl(ledger_path)
    require(ledger_report.get("rows") == 1 and len(ledger) == 1, "candidate ledger must contain one row")
    candidate = ledger[0]
    require(candidate.get("candidate_id") == "CAND-BENCH-TORCH-COMPILE-3407",
            "unexpected provisional candidate ID")
    require(candidate.get("promoted") == "pending" and candidate.get("anomaly_present") is None,
            "provisional candidate is mislabeled as confirmed/promoted")
    require(all(candidate.get(field) == "pending" for field in (
        "reproduced", "duplicate_checked", "minimized", "stable_tested", "nightly_tested"
    )), "a downstream candidate step was upgraded without evidence")
    for relative in candidate.get("artifact_paths", []):
        require((WORKSPACE_ROOT / relative).is_file(), f"candidate artifact is missing: {relative}")

    return {
        "result": "pass",
        "events": 960,
        "seeds": 2,
        "oracle_bearing": 89,
        "assertion_signals": 4,
        "invalid_oracle_rejections": 3,
        "provisional_candidates": 1,
        "promoted": 0,
        "full_campaign_ready": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--documentation", type=Path, default=DEFAULT_DOCUMENTATION)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = verify(args.events.resolve(), args.documentation.resolve(), args.checkpoint.resolve())
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
