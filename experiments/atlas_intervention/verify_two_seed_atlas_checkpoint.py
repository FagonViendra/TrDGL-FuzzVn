#!/usr/bin/env python3
"""Compact fail-closed verification of the two-seed Atlas evidence boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parents[1]
MANIFEST = HERE / "two_seed_checkpoint" / "atlas_blocker_manifest.json"
ATLAS_SNAPSHOT = HERE.parent / "vn_funnel" / "atlas_snapshot.json"
SOURCE_AUDIT = HERE / "source_recovery_search.md"
CANDIDATE_LEDGER = HERE.parent / "vn_funnel" / "two_seed_checkpoint" / "candidate_ledger.jsonl"
VALIDATION_SUMMARY = HERE / "validation_output" / "summary.validation.json"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(all(isinstance(row, dict) for row in rows), f"{path}: expected object rows")
    return rows


def verify() -> dict[str, Any]:
    manifest = load_json(MANIFEST)
    snapshot = load_json(ATLAS_SNAPSHOT)
    validation = load_json(VALIDATION_SUMMARY)
    candidates = load_jsonl(CANDIDATE_LEDGER)

    require(manifest.get("evidence_label") == "diagnostic_checkpoint", "wrong evidence label")
    require(manifest.get("ready_for_paper_result") is False, "Atlas checkpoint marked paper-ready")
    require(manifest.get("effectiveness_claim_allowed") is False, "Atlas effectiveness claim enabled")
    require(manifest["candidate_source"]["sha256"] == sha256(CANDIDATE_LEDGER),
            "candidate ledger hash mismatch")
    require(manifest["atlas_snapshot"]["sha256"] == sha256(ATLAS_SNAPSHOT),
            "Atlas snapshot hash mismatch")
    require(manifest["source_recovery_audit"]["sha256"] == sha256(SOURCE_AUDIT),
            "source-recovery audit hash mismatch")

    require(len(candidates) == 1, "expected one provisional candidate")
    candidate = candidates[0]
    require(candidate.get("candidate_id") == manifest["candidate_source"]["candidate_id"],
            "candidate ID mismatch")
    require(candidate.get("anomaly_present") is None and candidate.get("promoted") == "pending",
            "candidate was upgraded without evidence")

    audit = snapshot.get("source_audit", {})
    require(audit.get("raw_atlas_dataset_present_in_workspace") is False,
            "snapshot unexpectedly declares a raw Atlas")
    require(audit.get("independent_manifest_present_in_workspace") is False,
            "snapshot unexpectedly declares an independent manifest")
    require(snapshot.get("measured_duplicate_candidates") is None,
            "snapshot contains an unsupported duplicate count")
    require(snapshot.get("measured_atlas_guided_candidates") is None,
            "snapshot contains an unsupported guided count")

    duplicate = manifest["duplicate_triage"]
    planning = manifest["guided_planning"]
    require(duplicate.get("enabled_disabled_pair_count") == 0, "duplicate intervention pair exists")
    require(planning.get("enabled_disabled_pair_count") == 0, "planning intervention pair exists")
    for field in (
        "retrieval_matches", "duplicates_detected", "duplicates_rejected",
        "retrieval_precision", "candidate_duplicate_decision",
    ):
        require(duplicate.get(field) is None, f"duplicate metric {field} is not null")
    for field in (
        "atlas_guided_candidates", "enabled_only_reproduced_candidates",
        "unique_reproduced_per_1000_generations",
    ):
        require(planning.get(field) is None, f"planning metric {field} is not null")

    required_blockers = {
        "raw_atlas_dataset_absent", "independent_atlas_manifest_absent",
        "paired_duplicate_triage_not_run", "paired_guided_planning_not_run",
        "provisional_candidate_not_reproduced", "required_campaign_seeds_incomplete",
    }
    require(set(manifest.get("blockers", [])) == required_blockers, "Atlas blockers changed")
    require(validation.get("ready_for_paper_result") is False,
            "synthetic validation summary marked paper-ready")
    require({"raw_atlas_dataset_absent", "independent_atlas_manifest_absent"}.issubset(
        validation.get("blockers", [])
    ), "validation summary lost Atlas-source blockers")

    return {
        "result": "pass",
        "raw_atlas": False,
        "independent_manifest": False,
        "provisional_candidates": 1,
        "duplicate_pairs": 0,
        "planning_pairs": 0,
        "effectiveness_metrics": None,
        "paper_ready": False,
    }


def main() -> int:
    print(json.dumps(verify(), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
