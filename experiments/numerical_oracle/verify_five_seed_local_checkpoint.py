#!/usr/bin/env python3
"""Compact fail-closed verifier for the five-seed local oracle checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

import collect_numerical_oracle_results as collector


HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parents[1]
DEFAULT_ROOT = HERE / "five_seed_local_checkpoint"
SEEDS = (3407, 7711, 12011, 19001, 27103)
DEVICES = ("cpu", "cuda")
MODES = ("eager", "compiled")
CHECKS = ("forward", "gradient")
DTYPES = ("float32", "float64")
CONTROLS = ("clean", "injected")
TOLERANCES = (1e-5, 1e-4, 1e-3)


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
    require(isinstance(value, dict), f"{path}: expected JSON object")
    return value


def source_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PAPER_ROOT / path


def verify(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    diagnostic = load_json(root / "diagnostic_manifest.json")
    require(diagnostic.get("schema_version") == "trdgl_five_seed_local_numerical_checkpoint_v1",
            "wrong diagnostic schema")
    require(diagnostic.get("evidence_label") == "diagnostic_checkpoint", "wrong evidence label")
    require(diagnostic["tools"] == {
        "protocol_sha256": sha256(HERE / "run_numerical_oracle_protocol.py"),
        "collector_sha256": sha256(HERE / "collect_numerical_oracle_results.py"),
        "packager_sha256": sha256(HERE / "package_five_seed_local_checkpoint.py"),
    }, "tool hashes changed")

    for key in ("events", "run_manifest", "summary"):
        path = source_path(diagnostic["source"][f"{key}_path"])
        require(path.is_file(), f"source missing: {key}")
        require(sha256(path) == diagnostic["source"][f"{key}_sha256"], f"source hash mismatch: {key}")
    for name, expected in diagnostic["artifact_sha256"].items():
        path = root / name
        require(path.is_file(), f"artifact missing: {name}")
        require(sha256(path) == expected, f"artifact hash mismatch: {name}")

    events_path = root / "events.local_factorial.jsonl"
    rows = collector.load(events_path)
    require(len(rows) == 480, "event count is not 480")
    expected_keys = set(itertools.product(SEEDS, DEVICES, MODES, CHECKS, DTYPES, CONTROLS, TOLERANCES))
    actual = Counter((
        int(row["seed"]), row["device"], row["execution_mode"], row["check_kind"],
        row["input_dtype"], row["control_kind"], row["atol"],
    ) for row in rows)
    require(set(actual) == expected_keys and set(actual.values()) == {1}, "factorial event keys changed")
    require(all(row["tolerance_kind"] == "fixed" and row["certified_bound"] is None for row in rows),
            "unverified certified evidence appeared")

    statuses = Counter(row["status"] for row in rows)
    require(statuses == Counter({"unsupported": 240, "pass": 160, "fail": 80}),
            "event status counts changed")
    eager = [row for row in rows if row["execution_mode"] == "eager"]
    compiled = [row for row in rows if row["execution_mode"] == "compiled"]
    require(len(eager) == len(compiled) == 240, "mode counts changed")
    require(all(row["status"] in {"pass", "fail"} for row in eager), "eager has unresolved events")
    require(all(row["status"] == "unsupported" for row in compiled), "compiled was mislabeled measured")

    clean = [row for row in eager if row["control_kind"] == "clean"]
    injected = [row for row in eager if row["control_kind"] == "injected"]
    require(len(clean) == len(injected) == 120, "control counts changed")
    require(sum(row["status"] == "fail" for row in clean) == 0, "clean false-positive count changed")
    expected_detection = {1e-5: 40, 1e-4: 40, 1e-3: 0}
    observed_detection = {
        tolerance: sum(row["status"] == "fail" for row in injected if row["atol"] == tolerance)
        for tolerance in TOLERANCES
    }
    require(observed_detection == expected_detection, "injected detection counts changed")

    run = load_json(root / "run_manifest.json")
    require(run.get("run_id") == diagnostic.get("run_id") == rows[0]["run_id"], "run IDs disagree")
    require(run.get("evidence_label") == "local_validation", "run mislabeled as campaign")
    require(run.get("events_sha256") == sha256(events_path), "run event hash mismatch")
    require(run.get("protocol_script_sha256") == sha256(HERE / "run_numerical_oracle_protocol.py"),
            "run protocol hash mismatch")
    require(run.get("environment") == rows[0]["environment"] == diagnostic.get("environment"),
            "environment records disagree")
    probes = run["environment"].get("compiled_preflight", {})
    require({device: probes.get(device, {}).get("status") for device in DEVICES} == {
        "cpu": "unsupported", "cuda": "unsupported",
    }, "compiled preflight statuses changed")
    require(float(run.get("wall_seconds", 0)) > 0 and float(run.get("events_per_second", 0)) > 0,
            "runtime/throughput evidence is missing")
    require(abs(run["events_per_second"] - 480 / run["wall_seconds"]) < 1e-9,
            "throughput is inconsistent with wall time")

    summary = load_json(root / "summary.local_factorial.json")
    require(summary.get("source", {}).get("sha256") == sha256(events_path), "summary source hash mismatch")
    completeness = summary["completeness"]
    require(completeness.get("all_factorial_dimensions_present") is True, "designed dimensions are missing")
    require(completeness.get("all_factorial_dimensions_measured") is False,
            "unsupported compiled dimensions counted as measured")
    require(completeness.get("missing_measured_factorial_dimensions") == [
        [device, "compiled", check, dtype]
        for device in DEVICES for check in CHECKS for dtype in DTYPES
    ], "measured-dimension blocker set changed")
    require(completeness.get("all_required_seeds_present") is True, "five required seeds are not present")
    require(completeness.get("missing_matched_threshold_cell_count") == 120,
            "missing measured threshold-cell count changed")
    require(completeness.get("certified_bound_present") is False, "certificate appeared without source")
    require(completeness.get("ready_for_paper_result") is False, "summary marked paper-ready")

    results = diagnostic["results"]
    require(results["status_counts"] == {"fail": 80, "pass": 160, "unsupported": 240},
            "diagnostic status counts changed")
    require(results["eager"]["measured_events"] == 240, "eager measured count changed")
    require(results["eager"]["clean_false_positives"] == 0, "diagnostic clean FPs changed")
    require({row["tolerance"]: row["detected"] for row in results["eager"]["detection_by_tolerance"]}
            == expected_detection, "diagnostic detection table changed")
    require(results["compiled"]["measured_events"] == 0 and results["compiled"]["effect_estimate"] is None,
            "unsupported compiled cells received an effect estimate")
    require(diagnostic.get("certified_bound_present") is False, "diagnostic certificate flag changed")
    require(diagnostic.get("all_designed_dimensions_measured") is False, "diagnostic marked all dimensions measured")
    require(diagnostic.get("ready_for_paper_result") is False, "diagnostic marked paper-ready")

    return {
        "result": "pass",
        "events": 480,
        "seeds": 5,
        "eager_measured": 240,
        "compiled_unsupported": 240,
        "clean_false_positives": 0,
        "detected_1e_5": 40,
        "detected_1e_4": 40,
        "detected_1e_3": 0,
        "certified": False,
        "paper_ready": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(verify(args.root), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
