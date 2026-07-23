#!/usr/bin/env python3
"""Normalize and summarize TrDGL-FuzzVn candidate-gate evidence.

The implementation deliberately uses only the Python standard library so that
the same command runs locally and in a clean Colab runtime.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "trdgl_vn_funnel_v1"
IMPORTER_VERSION = "trdgl_benchmark_importer_v1"
STAGES = (
    "raw",
    "parseable",
    "ast_pass",
    "runnable",
    "target_valid",
    "oracle_bearing",
    "reproducible",
    "non_duplicate",
    "minimized",
    "stable_nightly",
    "promoted",
)

ALIASES = {
    "raw": ("raw",),
    "parseable": ("parseable", "parses"),
    "ast_pass": ("ast_pass", "ast_policy_pass"),
    "runnable": ("runnable",),
    "target_valid": ("target_valid", "target_call_present"),
    "oracle_bearing": ("oracle_bearing", "oracle_present"),
    "reproducible": ("reproducible", "reproduced"),
    "non_duplicate": ("non_duplicate",),
    "minimized": ("minimized",),
    "stable_nightly": ("stable_nightly",),
    "promoted": ("promoted",),
}

TRUE_STRINGS = {"1", "true", "yes", "pass", "passed"}
FALSE_STRINGS = {"0", "false", "no", "fail", "failed"}
UNKNOWN_STRINGS = {"", "-", "--", "na", "n/a", "none", "null", "pending", "unknown", "not_logged"}


class EvidenceError(ValueError):
    """Raised when a record violates the canonical evidence contract."""


def tri_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in TRUE_STRINGS:
            return True
        if token in FALSE_STRINGS:
            return False
        if token in UNKNOWN_STRINGS:
            return None
    raise EvidenceError(f"not a tri-state Boolean: {value!r}")


def first_present(record: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def first_present_name(record: dict[str, Any], names: Iterable[str]) -> str | None:
    for name in names:
        if name in record:
            return name
    return None


def derive_non_duplicate(record: dict[str, Any]) -> bool | None:
    direct = first_present(record, ALIASES["non_duplicate"])
    if direct is not None:
        return tri_bool(direct)
    cluster = record.get("duplicate_cluster")
    checked = tri_bool(record.get("duplicate_check_completed"))
    if checked is not True:
        return None
    return not bool(cluster)


def derive_stable_nightly(record: dict[str, Any]) -> bool | None:
    direct = first_present(record, ALIASES["stable_nightly"])
    if direct is not None:
        return tri_bool(direct)
    stable = tri_bool(record.get("stable_status"))
    nightly = tri_bool(record.get("nightly_status"))
    if stable is False or nightly is False:
        return False
    if stable is True and nightly is True:
        return True
    return None


def canonical_id(record: dict[str, Any]) -> str:
    existing = record.get("candidate_id") or record.get("event_id")
    if existing:
        return str(existing)
    payload = "\x1f".join(
        str(first_present(record, aliases) or "")
        for aliases in (
            ("run_id", "run_signature"),
            ("task_id",),
            ("baseline",),
            ("api",),
            ("generation_seed",),
            ("raw_output_hash", "raw_output_sha256"),
        )
    )
    return "evt-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize(record: dict[str, Any]) -> dict[str, Any]:
    stages: dict[str, bool | None] = {"raw": True}
    stage_evidence: dict[str, str | None] = {
        "raw": "raw_generation" if "raw_generation" in record else "record_presence"
    }
    for stage in STAGES[1:]:
        if stage == "non_duplicate":
            stages[stage] = derive_non_duplicate(record)
            if first_present_name(record, ALIASES[stage]):
                stage_evidence[stage] = first_present_name(record, ALIASES[stage])
            elif record.get("duplicate_check_completed") is not None:
                stage_evidence[stage] = "duplicate_check_completed+duplicate_cluster"
            else:
                stage_evidence[stage] = None
        elif stage == "stable_nightly":
            stages[stage] = derive_stable_nightly(record)
            if first_present_name(record, ALIASES[stage]):
                stage_evidence[stage] = first_present_name(record, ALIASES[stage])
            elif record.get("stable_status") is not None or record.get("nightly_status") is not None:
                stage_evidence[stage] = "stable_status+nightly_status"
            else:
                stage_evidence[stage] = None
        else:
            stages[stage] = tri_bool(first_present(record, ALIASES[stage]))
            stage_evidence[stage] = first_present_name(record, ALIASES[stage])

    # A later pass cannot repair an earlier failure. Unknown is retained: it is
    # missing evidence, not silently inferred evidence.
    earlier_false = None
    for stage in STAGES:
        if stages[stage] is False and earlier_false is None:
            earlier_false = stage
        elif stages[stage] is True and earlier_false is not None:
            raise EvidenceError(f"{stage}=true after {earlier_false}=false")

    if stages["promoted"] is True and record.get("anomaly_present") is not True:
        raise EvidenceError("promoted=true requires anomaly_present=true")

    rejection = record.get("rejection_reason")
    if not rejection:
        rejection = next((stage for stage in STAGES[1:] if stages[stage] is False), None)

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": canonical_id(record),
        "run_id": first_present(record, ("run_id", "run_signature")),
        "campaign": record.get("campaign"),
        "baseline": record.get("baseline"),
        "model_revision": first_present(record, ("model_revision", "model")),
        "api": record.get("api"),
        "api_group": record.get("api_group"),
        "generation_seed": record.get("generation_seed"),
        "task_id": record.get("task_id"),
        "started_utc": record.get("started_utc"),
        "finished_utc": record.get("finished_utc"),
        "prompt_sha256": first_present(record, ("prompt_sha256", "prompt_hash")),
        "raw_output_sha256": first_present(record, ("raw_output_sha256", "raw_output_hash")),
        "stages": stages,
        "stage_evidence": stage_evidence,
        "anomaly_present": tri_bool(record.get("anomaly_present")),
        "duplicate_cluster": record.get("duplicate_cluster"),
        "atlas_nearest_cluster": record.get("atlas_nearest_cluster"),
        "atlas_guided": tri_bool(record.get("atlas_guided")),
        "rejection_reason": rejection,
        "error_labels": record.get("error_labels", []),
        "generation_seconds": record.get("generation_seconds"),
        "subprocess_seconds": record.get("subprocess_seconds"),
        "evidence_source": record.get("evidence_source"),
        "source_sha256": record.get("source_sha256"),
        "source_record_index": record.get("source_record_index"),
        "importer_version": record.get("importer_version"),
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceError(f"{path}:{number}: {exc}") from exc
            if not isinstance(item, dict):
                raise EvidenceError(f"{path}:{number}: expected JSON object")
            records.append(item)
    return records


def validate_normalized(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceError(f"unexpected normalized schema: {record.get('schema_version')!r}")
    if not record.get("candidate_id"):
        raise EvidenceError("normalized record is missing candidate_id")
    if "run_id" not in record:
        raise EvidenceError("normalized record is missing run_id provenance")
    if record.get("source_sha256") is not None:
        value = record["source_sha256"]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
            raise EvidenceError("normalized source_sha256 must be a 64-character hex digest")
    if record.get("source_record_index") is not None and (
        not isinstance(record["source_record_index"], int) or record["source_record_index"] < 1
    ):
        raise EvidenceError("normalized source_record_index must be a positive integer")
    if record.get("importer_version") is not None and not isinstance(record["importer_version"], str):
        raise EvidenceError("normalized importer_version must be a string")
    raw_stages = record.get("stages")
    if not isinstance(raw_stages, dict):
        raise EvidenceError("normalized record is missing stages object")
    stages = {stage: tri_bool(raw_stages.get(stage)) for stage in STAGES}
    if stages["raw"] is not True:
        raise EvidenceError("normalized raw stage must be true")
    earlier_false = None
    for stage in STAGES:
        if stages[stage] is False and earlier_false is None:
            earlier_false = stage
        elif stages[stage] is True and earlier_false is not None:
            raise EvidenceError(f"normalized {stage}=true after {earlier_false}=false")
    if stages["promoted"] is True and record.get("anomaly_present") is not True:
        raise EvidenceError("normalized promoted=true requires anomaly_present=true")
    stage_evidence = record.get("stage_evidence")
    if not isinstance(stage_evidence, dict) or set(stage_evidence) != set(STAGES):
        raise EvidenceError("normalized stage_evidence must contain exactly every ordered stage")
    if any(value is not None and not isinstance(value, str) for value in stage_evidence.values()):
        raise EvidenceError("normalized stage_evidence values must be strings or null")
    labels = record.get("error_labels", [])
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise EvidenceError("normalized error_labels must be a list of strings")
    validated = dict(record)
    validated["stages"] = stages
    return validated


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [validate_normalized(r) if r.get("schema_version") == SCHEMA_VERSION else normalize(r) for r in records]
    ids = [r.get("candidate_id") for r in normalized]
    duplicates = [candidate_id for candidate_id, count in Counter(ids).items() if candidate_id is not None and count > 1]
    if duplicates:
        raise EvidenceError(f"duplicate candidate_id values: {duplicates[:5]}")
    stage_rows: list[dict[str, Any]] = []
    previous = None
    for stage in STAGES:
        values = [r["stages"].get(stage) for r in normalized]
        row: dict[str, Any] = {
            "stage": stage,
            "pass": sum(v is True for v in values),
            "fail": sum(v is False for v in values),
            "unknown": sum(v is None for v in values),
            "total": len(values),
        }
        # Do not turn missing gate evidence into a zero-yield rate. An all-raw
        # pass rate is defined only when every record has a known value.
        row["pass_rate_all_raw"] = row["pass"] / len(values) if values and row["unknown"] == 0 else None
        if previous is not None:
            eligible = [r for r in normalized if r["stages"].get(previous) is True]
            known = [r for r in eligible if r["stages"].get(stage) is not None]
            passed = sum(r["stages"].get(stage) is True for r in known)
            row["transition_from"] = previous
            row["transition_eligible"] = len(eligible)
            row["transition_known"] = len(known)
            row["transition_pass"] = passed
            row["transition_rate_known"] = passed / len(known) if known else None
        stage_rows.append(row)
        previous = stage

    rejection_counts = Counter(r.get("rejection_reason") or "not_recorded" for r in normalized)
    duplicate = {
        "checked_non_duplicate": sum(r["stages"]["non_duplicate"] is True for r in normalized),
        "duplicate_rejected": sum(r["stages"]["non_duplicate"] is False for r in normalized),
        "duplicate_status_unknown": sum(r["stages"]["non_duplicate"] is None for r in normalized),
        "cluster_ids_recorded": sum(bool(r.get("duplicate_cluster")) for r in normalized),
    }
    atlas = {
        "nearest_cluster_recorded": sum(bool(r.get("atlas_nearest_cluster")) for r in normalized),
        "atlas_guided_true": sum(r.get("atlas_guided") is True for r in normalized),
        "atlas_guided_false": sum(r.get("atlas_guided") is False for r in normalized),
        "atlas_guided_unknown": sum(r.get("atlas_guided") is None for r in normalized),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "records": len(normalized),
        "funnel": stage_rows,
        "rejection_reasons": dict(sorted(rejection_counts.items())),
        "vn_gate": duplicate,
        "atlas_intervention": atlas,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def write_funnel_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in report["funnel"]:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(report["funnel"])


def write_event_ledger_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "candidate_id", "run_id", "task_id", "baseline", "model_revision", "api", "api_group",
        "generation_seed", *STAGES, "anomaly_present", "duplicate_cluster", "atlas_nearest_cluster",
        "rejection_reason", "error_labels", "prompt_sha256", "raw_output_sha256",
        "generation_seconds", "subprocess_seconds", "evidence_source",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field) for field in fields}
            for stage in STAGES:
                row[stage] = record["stages"].get(stage)
            row["error_labels"] = ";".join(record.get("error_labels") or [])
            writer.writerow(row)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def import_benchmark_events(input_path: Path, output_dir: Path) -> dict[str, Any]:
    source = load_jsonl(input_path)
    source_hash = file_sha256(input_path)
    required = {
        "run_signature", "baseline", "task_id", "api", "api_group", "generation_seed",
        "raw_generation", "parseable", "ast_pass", "runnable", "target_valid", "oracle_bearing",
    }
    normalized: list[dict[str, Any]] = []
    for number, row in enumerate(source, 1):
        missing = sorted(required - row.keys())
        if missing:
            raise EvidenceError(f"{input_path}:{number}: missing benchmark fields: {missing}")
        if row["raw_generation"] is not True:
            raise EvidenceError(f"{input_path}:{number}: raw_generation must be true")
        for field in ("run_signature", "baseline", "task_id", "api", "api_group"):
            if not isinstance(row[field], str) or not row[field]:
                raise EvidenceError(f"{input_path}:{number}: {field} must be a non-empty string")
        item = normalize({
            **row,
            "evidence_source": f"benchmark_event:{input_path.name}:{number}",
            "source_sha256": source_hash,
            "source_record_index": number,
            "importer_version": IMPORTER_VERSION,
        })
        # The benchmark runner stops at oracle-bearing. Later states remain
        # null unless an input event explicitly carries the corresponding
        # evidence field; they are never inferred from successful execution.
        normalized.append(item)

    report = summarize(normalized)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "normalized_events.jsonl", normalized)
    write_event_ledger_csv(output_dir / "event_ledger.csv", normalized)
    write_json(output_dir / "funnel_report.json", report)
    write_funnel_csv(output_dir / "funnel_report.csv", report)
    manifest = {
        "schema_version": "trdgl_benchmark_import_v1",
        "importer_version": IMPORTER_VERSION,
        "input_path": str(input_path),
        "input_sha256": source_hash,
        "records": len(source),
        "run_signatures": sorted({str(row["run_signature"]) for row in source}),
        "baselines": dict(sorted(Counter(str(row["baseline"]) for row in source).items())),
        "downstream_policy": "reproducible/non_duplicate/minimized/stable_nightly/promoted remain null unless explicitly evidenced in the source event",
        "outputs": ["normalized_events.jsonl", "event_ledger.csv", "funnel_report.json", "funnel_report.csv"],
    }
    write_json(output_dir / "import_manifest.json", manifest)
    return manifest


def validate_ledger(path: Path) -> dict[str, Any]:
    rows = load_jsonl(path)
    ids: set[str] = set()
    allowed = {"yes", "no", "partial", "pending", "not_applicable"}
    promotion_allowed = {"yes", "no", "pending"}
    evidence_levels = {"workspace_artifact", "paper_only"}
    status_fields = ("reproduced", "duplicate_checked", "minimized", "stable_tested", "nightly_tested", "promoted")
    for number, row in enumerate(rows, 1):
        candidate_id = row.get("candidate_id")
        if not candidate_id or candidate_id in ids:
            raise EvidenceError(f"ledger row {number}: missing or duplicate candidate_id")
        ids.add(candidate_id)
        for field in ("candidate_family", "framework"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise EvidenceError(f"ledger row {number}: non-empty {field} is required")
        if "apis" in row and (
            not isinstance(row["apis"], list) or any(not isinstance(api, str) for api in row["apis"])
        ):
            raise EvidenceError(f"ledger row {number}: apis must be a list of strings")
        if not row.get("evidence_source"):
            raise EvidenceError(f"ledger row {number}: evidence_source is required")
        if row.get("evidence_level") not in evidence_levels:
            raise EvidenceError(f"ledger row {number}: invalid evidence_level")
        paths = row.get("artifact_paths")
        if not isinstance(paths, list):
            raise EvidenceError(f"ledger row {number}: artifact_paths must be a list")
        if any(not isinstance(path, str) or not path for path in paths):
            raise EvidenceError(f"ledger row {number}: artifact_paths must contain non-empty strings")
        if row["evidence_level"] == "workspace_artifact" and not paths:
            raise EvidenceError(f"ledger row {number}: workspace_artifact requires artifact_paths")
        for field in status_fields:
            if row.get(field) not in allowed:
                raise EvidenceError(f"ledger row {number}: invalid {field}={row.get(field)!r}")
        if row["promoted"] not in promotion_allowed:
            raise EvidenceError(f"ledger row {number}: invalid promoted={row['promoted']!r}")
        if row["promoted"] == "yes" and any(row[f] != "yes" for f in status_fields[:-1] if f != "stable_tested"):
            raise EvidenceError(f"ledger row {number}: promoted without completed mandatory checks")
    return {
        "schema_version": "trdgl_candidate_ledger_v1",
        "rows": len(rows),
        "status_counts": {
            field: dict(sorted(Counter(row[field] for row in rows).items())) for field in status_fields
        },
        "evidence_level_counts": dict(sorted(Counter(row["evidence_level"] for row in rows).items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    normal = sub.add_parser("normalize", help="normalize runner JSONL into canonical funnel JSONL")
    normal.add_argument("input", type=Path)
    normal.add_argument("output", type=Path)
    summary = sub.add_parser("summarize", help="write a funnel report from raw or normalized JSONL")
    summary.add_argument("input", type=Path)
    summary.add_argument("output", type=Path)
    summary.add_argument("--csv", type=Path)
    ledger = sub.add_parser("validate-ledger", help="validate the structured candidate ledger")
    ledger.add_argument("input", type=Path)
    ledger.add_argument("--output", type=Path)
    importer = sub.add_parser("import-benchmark", help="import benchmark events.jsonl without inferring downstream gate states")
    importer.add_argument("input", type=Path)
    importer.add_argument("output_dir", type=Path)
    normalized_validator = sub.add_parser("validate-normalized", help="fail-closed validation for canonical event JSONL")
    normalized_validator.add_argument("input", type=Path)
    normalized_validator.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "normalize":
            write_jsonl(args.output, (normalize(row) for row in load_jsonl(args.input)))
        elif args.command == "summarize":
            report = summarize(load_jsonl(args.input))
            write_json(args.output, report)
            if args.csv:
                write_funnel_csv(args.csv, report)
        elif args.command == "validate-ledger":
            report = validate_ledger(args.input)
            if args.output:
                write_json(args.output, report)
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "import-benchmark":
            manifest = import_benchmark_events(args.input, args.output_dir)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        else:
            records = [validate_normalized(row) for row in load_jsonl(args.input)]
            # summarize performs the duplicate-ID audit after per-row checks.
            report = summarize(records)
            result = {
                "schema_version": SCHEMA_VERSION,
                "valid_records": len(records),
                "unique_candidate_ids": len({row["candidate_id"] for row in records}),
                "funnel": report["funnel"],
            }
            if args.output:
                write_json(args.output, result)
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
