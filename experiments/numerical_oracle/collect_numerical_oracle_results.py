"""Validate and summarize numerical-oracle JSONL without filling missing cells."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED = {
    "schema_version", "run_id", "event_id", "evidence_label", "case_id", "seed",
    "device", "execution_mode", "execution_backend", "check_kind", "input_dtype",
    "reference_dtype", "control_kind", "injected_delta", "tolerance_kind", "atol",
    "rtol", "certified_bound", "certified_bound_source_sha256", "status",
    "abs_error_max", "rel_error_max",
    "ulp_error_max", "duration_seconds", "environment", "error",
}
STATUSES = {"pass", "fail", "error", "unsupported", "pending"}
EXPECTED_SEEDS = {3407, 7711, 12011, 19001, 27103}
REQUIRED_TOLERANCES = {1e-3, 1e-4, 1e-5}
EVENT_ID_FIELDS = (
    "run_id", "evidence_label", "case_id", "seed", "device", "execution_mode",
    "execution_backend", "check_kind", "input_dtype", "reference_dtype",
    "control_kind", "injected_delta", "tolerance_kind", "atol", "rtol",
    "certified_bound", "certified_bound_source_sha256",
)


def expected_event_id(row: dict[str, Any]) -> str:
    canonical = json.dumps(
        {key: row[key] for key in EVENT_ID_FIELDS}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(row: dict[str, Any], line_number: int) -> None:
    if set(row) != REQUIRED:
        raise ValueError(f"line {line_number}: fields mismatch: {sorted(set(row) ^ REQUIRED)}")
    if row["schema_version"] != "trdgl_numerical_oracle_event_v2":
        raise ValueError(f"line {line_number}: unknown schema")
    if row["event_id"] != expected_event_id(row):
        raise ValueError(f"line {line_number}: event_id does not match event design")
    if row["status"] not in STATUSES:
        raise ValueError(f"line {line_number}: bad status")
    if row["tolerance_kind"] == "fixed" and (row["atol"] is None or row["rtol"] is None):
        raise ValueError(f"line {line_number}: fixed tolerance lacks atol/rtol")
    if row["tolerance_kind"] == "certified":
        if row["certified_bound"] is None or row["certified_bound_source_sha256"] is None:
            raise ValueError(f"line {line_number}: certified tolerance lacks bound/source hash")
    elif row["certified_bound_source_sha256"] is not None:
        raise ValueError(f"line {line_number}: fixed tolerance carries certified source hash")
    source_hash = row["certified_bound_source_sha256"]
    if source_hash is not None and (
        not isinstance(source_hash, str) or len(source_hash) != 64
        or any(character not in "0123456789abcdef" for character in source_hash)
    ):
        raise ValueError(f"line {line_number}: invalid certified source SHA-256")
    for field in ("injected_delta", "atol", "rtol", "certified_bound", "abs_error_max", "rel_error_max", "duration_seconds"):
        value = row[field]
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"line {line_number}: {field} must be finite")
        if field != "injected_delta" and value is not None and value < 0:
            raise ValueError(f"line {line_number}: {field} must be non-negative")
    if row["ulp_error_max"] is not None and (
        not isinstance(row["ulp_error_max"], int) or row["ulp_error_max"] < 0
    ):
        raise ValueError(f"line {line_number}: ulp_error_max must be a non-negative integer")
    if row["status"] in {"pass", "fail"}:
        for field in ("abs_error_max", "rel_error_max", "ulp_error_max", "duration_seconds"):
            if row[field] is None:
                raise ValueError(f"line {line_number}: measured status lacks {field}")
    if row["status"] in {"error", "unsupported"} and not row["error"]:
        raise ValueError(f"line {line_number}: {row['status']} lacks error")
    if row["control_kind"] == "clean" and row["injected_delta"] is not None:
        raise ValueError(f"line {line_number}: clean control has injected_delta")


def load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            validate(row, line_number)
            if row["event_id"] in seen:
                raise ValueError(f"line {line_number}: duplicate event_id {row['event_id']}")
            seen.add(row["event_id"])
            rows.append(row)
    if not rows:
        raise ValueError("empty event stream")
    if len({row["run_id"] for row in rows}) != 1:
        raise ValueError("event stream contains multiple run IDs")
    if len({row["evidence_label"] for row in rows}) != 1:
        raise ValueError("event stream contains multiple evidence labels")
    environments = {json.dumps(row["environment"], sort_keys=True, separators=(",", ":")) for row in rows}
    if len(environments) != 1:
        raise ValueError("event stream contains multiple environments under one run ID")
    return rows


def summarize(path: Path) -> dict[str, Any]:
    rows = load(path)
    coverage = []
    dimensions = sorted({(row["device"], row["execution_mode"], row["check_kind"], row["input_dtype"], row["control_kind"]) for row in rows})
    for device, mode, check, dtype, control in dimensions:
        selected = [row for row in rows if (row["device"], row["execution_mode"], row["check_kind"], row["input_dtype"], row["control_kind"]) == (device, mode, check, dtype, control)]
        measured = [row for row in selected if row["status"] in {"pass", "fail"}]
        coverage.append({
            "device": device,
            "execution_mode": mode,
            "check_kind": check,
            "input_dtype": dtype,
            "control_kind": control,
            "events": len(selected),
            "measured": len(measured),
            "pass": sum(row["status"] == "pass" for row in selected),
            "fail": sum(row["status"] == "fail" for row in selected),
            "error": sum(row["status"] == "error" for row in selected),
            "unsupported": sum(row["status"] == "unsupported" for row in selected),
            "pending": sum(row["status"] == "pending" for row in selected),
            "max_abs_error": max((row["abs_error_max"] for row in measured), default=None),
            "max_rel_error": max((row["rel_error_max"] for row in measured), default=None),
            "max_ulp_error": max((row["ulp_error_max"] for row in measured), default=None),
        })
    statuses = Counter(row["status"] for row in rows)
    tolerances = sorted({row["atol"] for row in rows if row["tolerance_kind"] == "fixed" and row["atol"] is not None})
    expected_dimensions = {(device, mode, check, dtype) for device in ("cpu", "cuda") for mode in ("eager", "compiled") for check in ("forward", "gradient") for dtype in ("float32", "float64")}
    observed_dimensions = {(row["device"], row["execution_mode"], row["check_kind"], row["input_dtype"]) for row in rows}
    measured_dimensions = {
        (row["device"], row["execution_mode"], row["check_kind"], row["input_dtype"])
        for row in rows
        if row["control_kind"] == "clean" and row["tolerance_kind"] == "fixed"
        and row["status"] in {"pass", "fail"}
    }
    missing_dimensions = sorted(expected_dimensions - observed_dimensions)
    missing_measured_dimensions = sorted(expected_dimensions - measured_dimensions)
    observed_seeds = {row["seed"] for row in rows}
    measured_threshold_cells = {
        (
            row["device"], row["execution_mode"], row["check_kind"], row["input_dtype"],
            row["seed"], row["atol"],
        )
        for row in rows
        if row["control_kind"] == "clean" and row["tolerance_kind"] == "fixed"
        and row["status"] in {"pass", "fail"} and row["atol"] == row["rtol"]
    }
    expected_threshold_cells = {
        (device, mode, check, dtype, seed, tolerance)
        for device, mode, check, dtype in expected_dimensions
        for seed in EXPECTED_SEEDS
        for tolerance in REQUIRED_TOLERANCES
    }
    missing_threshold_cells = sorted(expected_threshold_cells - measured_threshold_cells)
    return {
        "schema_version": "trdgl_numerical_oracle_summary_v2",
        "evidence_label": rows[0]["evidence_label"],
        "run_id": rows[0]["run_id"],
        "source": {"path": path.as_posix(), "sha256": sha256(path), "events": len(rows)},
        "status_counts": {status: statuses.get(status, 0) for status in sorted(STATUSES)},
        "seeds": sorted(observed_seeds),
        "fixed_tolerances": tolerances,
        "certified_event_count": sum(row["tolerance_kind"] == "certified" for row in rows),
        "certified_bound_source_sha256": sorted({
            row["certified_bound_source_sha256"] for row in rows
            if row["certified_bound_source_sha256"] is not None
        }),
        "environment_sha256": hashlib.sha256(
            json.dumps(rows[0]["environment"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "coverage": coverage,
        "completeness": {
            "all_factorial_dimensions_present": not missing_dimensions,
            "missing_factorial_dimensions": [list(item) for item in missing_dimensions],
            "all_factorial_dimensions_measured": not missing_measured_dimensions,
            "missing_measured_factorial_dimensions": [list(item) for item in missing_measured_dimensions],
            "all_fixed_thresholds_present": REQUIRED_TOLERANCES.issubset(set(tolerances)),
            "all_required_seeds_present": EXPECTED_SEEDS.issubset(observed_seeds),
            "missing_required_seeds": sorted(EXPECTED_SEEDS - observed_seeds),
            "all_matched_threshold_cells_measured": not missing_threshold_cells,
            "missing_matched_threshold_cell_count": len(missing_threshold_cells),
            "missing_matched_threshold_cells": [list(item) for item in missing_threshold_cells],
            "certified_bound_present": any(row["tolerance_kind"] == "certified" for row in rows),
            "ready_for_paper_result": (
                rows[0]["evidence_label"] == "campaign"
                and not missing_threshold_cells
                and EXPECTED_SEEDS.issubset(observed_seeds)
                and any(row["tolerance_kind"] == "certified" for row in rows)
                and all(statuses.get(status, 0) == 0 for status in ("pending", "error", "unsupported"))
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = summarize(args.events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"result": "pass", "events": result["source"]["events"], "ready_for_paper_result": result["completeness"]["ready_for_paper_result"]}, indent=2))


if __name__ == "__main__":
    main()
