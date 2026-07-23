#!/usr/bin/env python3
"""Package the five-seed local numerical-oracle run as diagnostic evidence."""

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
EXPECTED_SEEDS = (3407, 7711, 12011, 19001, 27103)
DEVICES = ("cpu", "cuda")
MODES = ("eager", "compiled")
CHECKS = ("forward", "gradient")
DTYPES = ("float32", "float64")
CONTROLS = ("clean", "injected")
TOLERANCES = (1e-5, 1e-4, 1e-3)


class PackagingError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackagingError(message)


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


def portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PAPER_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    require(len(rows) == 480, "local factorial must contain 480 events")
    expected_keys = set(itertools.product(
        EXPECTED_SEEDS, DEVICES, MODES, CHECKS, DTYPES, CONTROLS, TOLERANCES,
    ))
    actual_keys = Counter((
        int(row["seed"]), row["device"], row["execution_mode"], row["check_kind"],
        row["input_dtype"], row["control_kind"], row["atol"],
    ) for row in rows)
    require(set(actual_keys) == expected_keys and set(actual_keys.values()) == {1},
            "event stream is not the exact five-seed fixed-threshold factorial")
    require(all(row["tolerance_kind"] == "fixed" for row in rows),
            "local diagnostic unexpectedly contains certified events")

    eager = [row for row in rows if row["execution_mode"] == "eager"]
    compiled = [row for row in rows if row["execution_mode"] == "compiled"]
    require(len(eager) == len(compiled) == 240, "eager/compiled event counts are not balanced")
    require(all(row["status"] in {"pass", "fail"} for row in eager),
            "an eager event is unresolved")
    require(all(row["status"] == "unsupported" for row in compiled),
            "compiled boundary is not uniformly unsupported")

    clean = [row for row in eager if row["control_kind"] == "clean"]
    injected = [row for row in eager if row["control_kind"] == "injected"]
    require(len(clean) == len(injected) == 120, "clean/injected eager counts are not balanced")
    require(all(row["status"] == "pass" for row in clean), "a clean eager control failed")

    detection_by_tolerance: list[dict[str, Any]] = []
    for tolerance in TOLERANCES:
        selected = [row for row in injected if row["atol"] == tolerance]
        detected = sum(row["status"] == "fail" for row in selected)
        detection_by_tolerance.append({
            "tolerance": tolerance,
            "injected_events": len(selected),
            "detected": detected,
            "missed": len(selected) - detected,
            "detection_rate": detected / len(selected),
        })

    clean_error_bounds: list[dict[str, Any]] = []
    for device, check, dtype in itertools.product(DEVICES, CHECKS, DTYPES):
        selected = [
            row for row in clean
            if (row["device"], row["check_kind"], row["input_dtype"]) == (device, check, dtype)
        ]
        require(len(selected) == 15, f"clean coverage mismatch for {(device, check, dtype)}")
        clean_error_bounds.append({
            "device": device,
            "check": check,
            "dtype": dtype,
            "events": len(selected),
            "max_abs_error": max(row["abs_error_max"] for row in selected),
            "max_rel_error": max(row["rel_error_max"] for row in selected),
            "max_ulp_error": max(row["ulp_error_max"] for row in selected),
        })

    return {
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "eager": {
            "measured_events": len(eager),
            "clean_events": len(clean),
            "clean_false_positives": sum(row["status"] == "fail" for row in clean),
            "clean_false_positive_rate": 0.0,
            "injected_events": len(injected),
            "detection_by_tolerance": detection_by_tolerance,
            "clean_error_bounds": clean_error_bounds,
        },
        "compiled": {
            "events": len(compiled),
            "measured_events": 0,
            "unsupported_events": len(compiled),
            "effect_estimate": None,
        },
    }


def write_checkpoint(path: Path, manifest: dict[str, Any]) -> None:
    results = manifest["results"]
    rates = {row["tolerance"]: row for row in results["eager"]["detection_by_tolerance"]}
    env = manifest["environment"]
    lines = [
        "# Five-seed local numerical-oracle diagnostic",
        "",
        "This is a complete local-validation design, not a complete measured paper factorial.",
        "",
        "## Coverage and outcomes",
        "",
        f"- 480 designed events across five seeds, CPU/CUDA, eager/compiled, forward/gradient, float32/float64, clean/injected, and three fixed tolerances.",
        f"- Eager measured: {results['eager']['measured_events']}/240; compiled measured: 0/240 (all compiled cells are explicitly unsupported on this Windows host).",
        f"- Clean eager controls: {results['eager']['clean_false_positives']}/{results['eager']['clean_events']} false positives.",
        f"- Injected delta 2e-4 detection: {rates[1e-5]['detected']}/40 at 1e-5, {rates[1e-4]['detected']}/40 at 1e-4, and {rates[1e-3]['detected']}/40 at 1e-3.",
        f"- Protocol wall time: {manifest['runtime']['wall_seconds']:.6f} s ({manifest['runtime']['events_per_second']:.3f} designed events/s; interpreter import excluded).",
        "",
        "## Environment",
        "",
        f"- Python {env['python']}; PyTorch {env['torch']}; CUDA runtime {env['cuda_runtime']}; driver {env['driver_version']}.",
        f"- GPU: {env['gpu']}.",
        "",
        "## Clean-control numerical maxima",
        "",
        "| Device | Check | Dtype | Max abs | Max rel | Max ULP |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in results["eager"]["clean_error_bounds"]:
        lines.append(
            f"| {row['device']} | {row['check']} | {row['dtype']} | "
            f"{row['max_abs_error']:.6g} | {row['max_rel_error']:.6g} | {row['max_ulp_error']} |"
        )
    lines.extend(["", "## Claim boundary", "", manifest["claim_boundary"], ""])
    path.write_bytes("\n".join(lines).encode("utf-8"))


def package(events_path: Path, run_manifest_path: Path, summary_path: Path, output_path: Path) -> dict[str, Any]:
    events_path = events_path.resolve()
    run_manifest_path = run_manifest_path.resolve()
    summary_path = summary_path.resolve()
    output_path = output_path.resolve()
    rows = collector.load(events_path)
    run = load_json(run_manifest_path)
    summary = load_json(summary_path)
    results = analyze(rows)

    require(run.get("schema_version") == "trdgl_numerical_oracle_run_v1", "wrong run-manifest schema")
    require(run.get("evidence_label") == "local_validation", "run is not labeled local validation")
    require(run.get("events") == 480 and run.get("events_sha256") == sha256(events_path),
            "run manifest does not bind the 480-event stream")
    require(run.get("status_counts") == results["status_counts"], "run status counts changed")
    require(run.get("environment") == rows[0]["environment"], "run/event environment mismatch")
    require(run.get("protocol_script_sha256") == sha256(HERE / "run_numerical_oracle_protocol.py"),
            "protocol script hash mismatch")
    require(summary.get("source", {}).get("sha256") == sha256(events_path), "summary input hash mismatch")
    require(summary.get("status_counts") == {
        "error": 0, "fail": 80, "pass": 160, "pending": 0, "unsupported": 240,
    }, "summary status counts changed")
    completeness = summary["completeness"]
    require(completeness.get("all_factorial_dimensions_present") is True,
            "not all designed dimensions are represented")
    require(completeness.get("all_factorial_dimensions_measured") is False,
            "unsupported compiled cells were counted as measured")
    require(completeness.get("all_required_seeds_present") is True, "five-seed coverage is incomplete")
    require(completeness.get("missing_matched_threshold_cell_count") == 120,
            "missing measured threshold-cell count changed")
    require(completeness.get("certified_bound_present") is False, "unsupported certificate appeared")
    require(completeness.get("ready_for_paper_result") is False, "local diagnostic marked paper-ready")

    probes = run["environment"].get("compiled_preflight", {})
    require({device: probes.get(device, {}).get("status") for device in DEVICES} == {
        "cpu": "unsupported", "cuda": "unsupported",
    }, "compiled preflight boundary changed")

    checkpoint_path = output_path.parent / "checkpoint.md"
    manifest: dict[str, Any] = {
        "schema_version": "trdgl_five_seed_local_numerical_checkpoint_v1",
        "evidence_label": "diagnostic_checkpoint",
        "source": {
            "events_path": portable(events_path),
            "events_sha256": sha256(events_path),
            "run_manifest_path": portable(run_manifest_path),
            "run_manifest_sha256": sha256(run_manifest_path),
            "summary_path": portable(summary_path),
            "summary_sha256": sha256(summary_path),
        },
        "tools": {
            "protocol_sha256": sha256(HERE / "run_numerical_oracle_protocol.py"),
            "collector_sha256": sha256(HERE / "collect_numerical_oracle_results.py"),
            "packager_sha256": sha256(Path(__file__)),
        },
        "run_id": run["run_id"],
        "design": run["design"],
        "environment": run["environment"],
        "runtime": {
            "wall_seconds": run["wall_seconds"],
            "events_per_second": run["events_per_second"],
            "scope": "argument-validated protocol body through event-file flush; interpreter/module import excluded",
        },
        "results": results,
        "all_designed_dimensions_present": True,
        "all_designed_dimensions_measured": False,
        "certified_bound_present": False,
        "ready_for_paper_result": False,
        "blockers": [
            "local_validation_not_campaign",
            "cpu_compiled_unsupported",
            "cuda_compiled_unsupported",
            "certified_bound_source_absent",
        ],
        "claim_boundary": "Complete five-seed local diagnostic design only. CPU/CUDA eager cells are measured; compiled cells are unsupported and certified-bound evidence is absent, so this is not the matched paper result.",
    }
    write_checkpoint(checkpoint_path, manifest)
    manifest["artifact_sha256"] = {
        events_path.name: sha256(events_path),
        run_manifest_path.name: sha256(run_manifest_path),
        summary_path.name: sha256(summary_path),
        checkpoint_path.name: sha256(checkpoint_path),
    }
    output_path.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_ROOT / "events.local_factorial.jsonl")
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_ROOT / "run_manifest.json")
    parser.add_argument("--summary", type=Path, default=DEFAULT_ROOT / "summary.local_factorial.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "diagnostic_manifest.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = package(args.events, args.run_manifest, args.summary, args.output)
    rates = {row["tolerance"]: row["detected"] for row in manifest["results"]["eager"]["detection_by_tolerance"]}
    print(json.dumps({
        "result": "pass",
        "events": 480,
        "eager_measured": 240,
        "compiled_unsupported": 240,
        "clean_false_positives": 0,
        "detected_1e_5": rates[1e-5],
        "detected_1e_4": rates[1e-4],
        "detected_1e_3": rates[1e-3],
        "paper_ready": False,
    }, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
