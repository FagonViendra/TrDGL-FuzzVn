#!/usr/bin/env python3
"""Append-only candidate verification workflow with a hash-chained audit log."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import vn_funnel


AUDIT_SCHEMA = "trdgl_candidate_audit_v1"
GENESIS_HASH = "0" * 64
STEPS = ("reproducible", "duplicate_checked", "minimized", "stable_tested", "nightly_tested")
STATUSES = {"pending", "partial", "passed", "failed", "not_applicable"}
LEDGER_STATUS_MAP = {
    "yes": "passed", "no": "failed", "partial": "partial",
    "pending": "pending", "not_applicable": "not_applicable",
}
LEDGER_STEP_FIELDS = {
    "reproducible": "reproduced",
    "duplicate_checked": "duplicate_checked",
    "minimized": "minimized",
    "stable_tested": "stable_tested",
    "nightly_tested": "nightly_tested",
}


class WorkflowError(ValueError):
    pass


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def event_hash(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "event_sha256"}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def iso_timestamp(value: str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise WorkflowError("timestamp must include a timezone")
    return parsed.isoformat()


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return vn_funnel.load_jsonl(path)
    except vn_funnel.EvidenceError as exc:
        raise WorkflowError(str(exc)) from exc


def verify_evidence(evidence: Any, verify_artifacts: bool) -> None:
    if not isinstance(evidence, dict):
        raise WorkflowError("evidence object is required")
    for field in ("artifact_path", "artifact_sha256", "timestamp_utc", "tool", "tool_version"):
        if not isinstance(evidence.get(field), str) or not evidence[field]:
            raise WorkflowError(f"evidence.{field} is required")
    iso_timestamp(evidence["timestamp_utc"])
    digest = evidence["artifact_sha256"]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        raise WorkflowError("evidence.artifact_sha256 is not SHA-256")
    if verify_artifacts:
        path = Path(evidence["artifact_path"])
        if not path.is_file():
            raise WorkflowError(f"evidence artifact is missing: {path}")
        if file_hash(path) != digest:
            raise WorkflowError(f"evidence artifact hash mismatch: {path}")


def blank_state() -> dict[str, Any]:
    return {
        "steps": {step: {"status": "pending", "verified_in_audit": False} for step in STEPS},
        "promoted": False,
    }


def replay(path: Path, verify_artifacts: bool = True) -> dict[str, Any]:
    events = read_log(path)
    states: dict[str, dict[str, Any]] = {}
    previous = GENESIS_HASH
    for expected_sequence, event in enumerate(events, 1):
        if event.get("audit_schema") != AUDIT_SCHEMA:
            raise WorkflowError(f"event {expected_sequence}: wrong audit schema")
        if event.get("sequence") != expected_sequence:
            raise WorkflowError(f"event {expected_sequence}: non-contiguous sequence")
        if event.get("prev_event_sha256") != previous:
            raise WorkflowError(f"event {expected_sequence}: broken previous-hash link")
        if event.get("event_sha256") != event_hash(event):
            raise WorkflowError(f"event {expected_sequence}: event hash mismatch")
        if not isinstance(event.get("timestamp_utc"), str) or not event["timestamp_utc"]:
            raise WorkflowError(f"event {expected_sequence}: timestamp_utc is required")
        iso_timestamp(event["timestamp_utc"])
        candidate_id = event.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise WorkflowError(f"event {expected_sequence}: candidate_id is required")
        action = event.get("action")
        if action == "register":
            if candidate_id in states:
                raise WorkflowError(f"event {expected_sequence}: duplicate registration")
            initial = event.get("initial_state")
            if not isinstance(initial, dict) or set(initial) != set(STEPS):
                raise WorkflowError(f"event {expected_sequence}: invalid initial state")
            state = blank_state()
            for step in STEPS:
                status = initial[step]
                if status not in STATUSES:
                    raise WorkflowError(f"event {expected_sequence}: invalid initial {step}")
                state["steps"][step] = {"status": status, "verified_in_audit": False}
            state["candidate_family"] = event.get("candidate_family")
            states[candidate_id] = state
        elif action == "update_step":
            if candidate_id not in states:
                raise WorkflowError(f"event {expected_sequence}: update before registration")
            if states[candidate_id]["promoted"]:
                raise WorkflowError(f"event {expected_sequence}: update after promotion")
            step = event.get("step")
            status = event.get("status")
            if step not in STEPS or status not in STATUSES or status == "pending":
                raise WorkflowError(f"event {expected_sequence}: invalid step update")
            verify_evidence(event.get("evidence"), verify_artifacts)
            current = states[candidate_id]["steps"][step]
            if current["verified_in_audit"] and not legal_transition(current["status"], status):
                raise WorkflowError(f"event {expected_sequence}: illegal {step} transition {current['status']} -> {status}")
            current.update({"status": status, "verified_in_audit": True, "event_sequence": expected_sequence})
        elif action == "promote":
            if candidate_id not in states:
                raise WorkflowError(f"event {expected_sequence}: promotion before registration")
            verify_evidence(event.get("evidence"), verify_artifacts)
            missing = promotion_blockers(states[candidate_id])
            if missing:
                raise WorkflowError(f"event {expected_sequence}: promotion gate blocked: {missing}")
            if states[candidate_id]["promoted"]:
                raise WorkflowError(f"event {expected_sequence}: duplicate promotion")
            states[candidate_id]["promoted"] = True
            states[candidate_id]["promotion_event_sequence"] = expected_sequence
        else:
            raise WorkflowError(f"event {expected_sequence}: unknown action {action!r}")
        previous = event["event_sha256"]
    return {"events": events, "states": states, "head_sha256": previous}


def legal_transition(old: str, new: str) -> bool:
    if old == new:
        return False
    if old == "pending":
        return new in {"partial", "passed", "failed", "not_applicable"}
    if old in {"partial", "failed"}:
        return new in {"partial", "passed", "failed"} - {old}
    return False


def promotion_blockers(state: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for step in STEPS:
        item = state["steps"][step]
        if item["status"] != "passed":
            blockers.append(f"{step}={item['status']}")
        elif not item["verified_in_audit"]:
            blockers.append(f"{step}=legacy_without_audit_evidence")
    return blockers


def make_evidence(artifact: Path, tool: str, tool_version: str, timestamp: str | None, notes: str | None) -> dict[str, Any]:
    resolved = artifact.resolve()
    if not resolved.is_file():
        raise WorkflowError(f"evidence artifact is missing: {resolved}")
    if not tool or not tool_version:
        raise WorkflowError("tool and tool_version are required")
    return {
        "artifact_path": str(resolved),
        "artifact_sha256": file_hash(resolved),
        "timestamp_utc": iso_timestamp(timestamp),
        "tool": tool,
        "tool_version": tool_version,
        "notes": notes or "",
    }


def append_event(path: Path, body: dict[str, Any]) -> dict[str, Any]:
    audit = replay(path, verify_artifacts=True)
    event = {
        "audit_schema": AUDIT_SCHEMA,
        "sequence": len(audit["events"]) + 1,
        "prev_event_sha256": audit["head_sha256"],
        **body,
    }
    event["event_sha256"] = event_hash(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    # Verify the appended bytes and resulting transition before returning.
    replay(path, verify_artifacts=True)
    return event


def import_ledger(ledger_path: Path, log_path: Path) -> int:
    if log_path.exists() and log_path.stat().st_size:
        raise WorkflowError("import requires a new empty audit log")
    vn_funnel.validate_ledger(ledger_path)
    rows = vn_funnel.load_jsonl(ledger_path)
    ledger_sha = file_hash(ledger_path)
    for row in rows:
        if row["promoted"] == "yes":
            raise WorkflowError("legacy promoted rows require a separate audited migration")
        initial = {step: LEDGER_STATUS_MAP[row[LEDGER_STEP_FIELDS[step]]] for step in STEPS}
        append_event(log_path, {
            "candidate_id": row["candidate_id"],
            "candidate_family": row["candidate_family"],
            "action": "register",
            "timestamp_utc": iso_timestamp(),
            "initial_state": initial,
            "legacy_import": True,
            "source_ledger_path": str(ledger_path.resolve()),
            "source_ledger_sha256": ledger_sha,
            "source_evidence": row["evidence_source"],
        })
    return len(rows)


def update_step(log_path: Path, candidate_id: str, step: str, status: str, evidence: dict[str, Any]) -> dict[str, Any]:
    audit = replay(log_path, verify_artifacts=True)
    if candidate_id not in audit["states"]:
        raise WorkflowError(f"unknown candidate: {candidate_id}")
    if audit["states"][candidate_id]["promoted"]:
        raise WorkflowError("promoted candidates are immutable; register a new candidate/version for retest")
    if step not in STEPS or status not in STATUSES or status == "pending":
        raise WorkflowError("invalid step or status")
    current = audit["states"][candidate_id]["steps"][step]
    # A legacy imported value may be re-attested at the same status. Once an
    # audited result exists, duplicate or regressive transitions are rejected.
    if current["verified_in_audit"] and not legal_transition(current["status"], status):
        raise WorkflowError(f"illegal transition: {current['status']} -> {status}")
    return append_event(log_path, {
        "candidate_id": candidate_id,
        "action": "update_step",
        "step": step,
        "status": status,
        "timestamp_utc": evidence["timestamp_utc"],
        "evidence": evidence,
    })


def promote(log_path: Path, candidate_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    audit = replay(log_path, verify_artifacts=True)
    if candidate_id not in audit["states"]:
        raise WorkflowError(f"unknown candidate: {candidate_id}")
    blockers = promotion_blockers(audit["states"][candidate_id])
    if blockers:
        raise WorkflowError("promotion gate blocked: " + ", ".join(blockers))
    return append_event(log_path, {
        "candidate_id": candidate_id,
        "action": "promote",
        "timestamp_utc": evidence["timestamp_utc"],
        "evidence": evidence,
    })


def state_report(log_path: Path, verify_artifacts: bool = True) -> dict[str, Any]:
    audit = replay(log_path, verify_artifacts=verify_artifacts)
    return {
        "audit_schema": AUDIT_SCHEMA,
        "events": len(audit["events"]),
        "head_sha256": audit["head_sha256"],
        "candidates": audit["states"],
    }


def add_evidence_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--tool-version", required=True)
    parser.add_argument("--timestamp")
    parser.add_argument("--notes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("import-ledger")
    init.add_argument("ledger", type=Path)
    init.add_argument("audit_log", type=Path)
    update = sub.add_parser("update")
    update.add_argument("audit_log", type=Path)
    update.add_argument("candidate_id")
    update.add_argument("step", choices=STEPS)
    update.add_argument("status", choices=sorted(STATUSES - {"pending"}))
    add_evidence_args(update)
    promotion = sub.add_parser("promote")
    promotion.add_argument("audit_log", type=Path)
    promotion.add_argument("candidate_id")
    add_evidence_args(promotion)
    verify = sub.add_parser("verify")
    verify.add_argument("audit_log", type=Path)
    verify.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "import-ledger":
            print(json.dumps({"imported": import_ledger(args.ledger, args.audit_log)}))
        elif args.command == "update":
            evidence = make_evidence(args.artifact, args.tool, args.tool_version, args.timestamp, args.notes)
            print(json.dumps(update_step(args.audit_log, args.candidate_id, args.step, args.status, evidence), ensure_ascii=False))
        elif args.command == "promote":
            evidence = make_evidence(args.artifact, args.tool, args.tool_version, args.timestamp, args.notes)
            print(json.dumps(promote(args.audit_log, args.candidate_id, evidence), ensure_ascii=False))
        else:
            report = state_report(args.audit_log, verify_artifacts=True)
            if args.output:
                vn_funnel.write_json(args.output, report)
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
    except (WorkflowError, vn_funnel.EvidenceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
