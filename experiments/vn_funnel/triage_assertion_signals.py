#!/usr/bin/env python3
"""Extract assertion-failure signals and build local semantic replay evidence.

The benchmark's ``runnable`` field means exit code zero, so a program whose
oracle raises AssertionError does not reach ``oracle_bearing``.  Such a record
is only a triage signal: it can be an invalid generated oracle, an environment
failure, or a real framework discrepancy.  This tool never promotes a signal
or silently sets ``anomaly_present=true``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any


TOOL_VERSION = "trdgl_assertion_signal_triage_v1"
ASSERTION_MARKER = "AssertionError"
ENVIRONMENT_FAILURE_MARKERS = (
    "BackendCompilerFailed",
    "Cannot find a working triton installation",
    "CUDA driver",
    "CUDA runtime",
    "ModuleNotFoundError",
    "ImportError",
)
DECISION_ANOMALY_CONTRACT = {
    "rejected_invalid_oracle": False,
    "pending_pinned_environment_replay": None,
    "confirmed_anomaly_candidate": True,
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_jsonl_snapshot(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: input is not UTF-8: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: record must be an object")
        row = dict(row)
        row["_source_record_index"] = line_number
        rows.append(row)
    return rows, payload


def is_assertion_signal(row: dict[str, Any]) -> bool:
    exit_code = row.get("exit_code")
    return (
        row.get("parseable") is True
        and row.get("target_call_present") is True
        and row.get("oracle_present") is True
        and row.get("fake_assertion") is False
        and isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
        and ASSERTION_MARKER in str(row.get("stderr") or "")
    )


def signal_id(row: dict[str, Any]) -> str:
    identity = "\x1f".join(
        str(row.get(field) or "")
        for field in (
            "run_signature", "baseline", "task_id", "api", "generation_seed", "raw_output_sha256"
        )
    )
    return "sig-assert-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def extract_signals(rows: list[dict[str, Any]], source_sha256: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for row in rows:
        if not is_assertion_signal(row):
            continue
        code = str(row.get("extracted_code") or "")
        signals.append({
            "schema_version": TOOL_VERSION,
            "signal_id": signal_id(row),
            "signal_kind": "assertion_failure",
            "source_sha256": source_sha256,
            "source_record_index": row["_source_record_index"],
            "run_signature": row.get("run_signature"),
            "task_id": row.get("task_id"),
            "baseline": row.get("baseline"),
            "api": row.get("api"),
            "api_group": row.get("api_group"),
            "generation_seed": row.get("generation_seed"),
            "raw_output_sha256": row.get("raw_output_sha256"),
            "extracted_code_sha256": sha256_bytes(code.encode("utf-8")),
            "extracted_code": code,
            "original_exit_code": row.get("exit_code"),
            "original_stdout": row.get("stdout") or "",
            "original_stderr": row.get("stderr") or "",
            "original_stages": {
                name: row.get(name)
                for name in (
                    "raw_generation", "parseable", "ast_pass", "runnable",
                    "target_valid", "oracle_bearing",
                )
            },
            "target_call_present": row.get("target_call_present"),
            "oracle_present": row.get("oracle_present"),
            "fake_assertion": row.get("fake_assertion"),
            "anomaly_present": None,
            "triage_status": "needs_oracle_validation",
            "downstream_gate": {
                "reproducible": None,
                "non_duplicate": None,
                "minimized": None,
                "stable_nightly": None,
                "promoted": None,
            },
        })
    return signals


def validate_decisions(
    signals: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    signal_ids = {signal["signal_id"] for signal in signals}
    seen: set[str] = set()
    decision_counts: Counter[str] = Counter()
    anomaly_counts: Counter[str] = Counter()
    provisional_candidates: list[str] = []
    for line_number, decision in enumerate(decisions, 1):
        sid = decision.get("signal_id")
        if not isinstance(sid, str) or sid not in signal_ids:
            raise ValueError(f"decision {line_number}: unknown or missing signal_id")
        if sid in seen:
            raise ValueError(f"decision {line_number}: duplicate signal_id {sid}")
        seen.add(sid)
        status = decision.get("decision")
        if status not in DECISION_ANOMALY_CONTRACT:
            raise ValueError(f"decision {line_number}: invalid decision {status!r}")
        expected_anomaly = DECISION_ANOMALY_CONTRACT[status]
        if decision.get("anomaly_present") is not expected_anomaly:
            raise ValueError(
                f"decision {line_number}: {status} requires anomaly_present={expected_anomaly!r}"
            )
        if decision.get("promoted") is not False:
            raise ValueError(f"decision {line_number}: triage decisions must set promoted=false")
        if not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip():
            raise ValueError(f"decision {line_number}: non-empty rationale is required")
        evidence = decision.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(item, str) and item for item in evidence
        ):
            raise ValueError(f"decision {line_number}: evidence_refs must be non-empty strings")
        candidate_id = decision.get("candidate_id")
        if candidate_id is not None:
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ValueError(f"decision {line_number}: candidate_id must be non-empty")
            provisional_candidates.append(candidate_id)
        decision_counts[str(status)] += 1
        anomaly_counts[
            "true" if expected_anomaly is True else "false" if expected_anomaly is False else "unknown"
        ] += 1
    missing = sorted(signal_ids - seen)
    if missing:
        raise ValueError(f"decisions are missing signal IDs: {missing}")
    if len(set(provisional_candidates)) != len(provisional_candidates):
        raise ValueError("candidate_id values must be unique")
    return {
        "decision_counts": dict(sorted(decision_counts.items())),
        "anomaly_counts": {
            name: anomaly_counts.get(name, 0) for name in ("true", "false", "unknown")
        },
        "provisional_candidate_count": len(provisional_candidates),
        "provisional_candidate_ids": sorted(provisional_candidates),
        "promoted_count": 0,
        "independent_review_complete": False,
    }


def benchmark_funnel_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stages = ("raw_generation", "parseable", "ast_pass", "runnable", "target_valid", "oracle_bearing")
    result: list[dict[str, Any]] = []
    for stage in stages:
        values = [row.get(stage) for row in rows]
        result.append({
            "stage": "raw" if stage == "raw_generation" else stage,
            "pass": sum(value is True for value in values),
            "fail": sum(value is False for value in values),
            "unknown": sum(value is None for value in values),
            "total": len(values),
        })
    return result


def local_environment() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }
    try:
        import torch

        result.update({
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        })
    except Exception as exc:  # pragma: no cover - depends on host environment
        result["torch_import_error"] = f"{type(exc).__name__}: {exc}"
    return result


def classify_replay(return_code: int | None, stderr: str, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    if return_code == 0:
        return "pass"
    if ASSERTION_MARKER in stderr:
        return "assertion_failure"
    if any(marker.lower() in stderr.lower() for marker in ENVIRONMENT_FAILURE_MARKERS):
        return "environment_unsupported"
    return "other_failure"


def replay_signal(signal: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    code = str(signal.get("extracted_code") or "")
    with tempfile.TemporaryDirectory(prefix="trdgl-assertion-replay-") as temp:
        script = Path(temp) / "candidate.py"
        script.write_text(code, encoding="utf-8", newline="\n")
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=env,
                check=False,
            )
            elapsed = time.perf_counter() - started
            return_code: int | None = completed.returncode
            stdout, stderr, timed_out = completed.stdout, completed.stderr, False
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            return_code, timed_out = None, True
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    return {
        "signal_id": signal["signal_id"],
        "api": signal["api"],
        "status": classify_replay(return_code, stderr, timed_out),
        "return_code": return_code,
        "timed_out": timed_out,
        "elapsed_seconds": round(elapsed, 6),
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": sha256_bytes(stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
    }


def semantic_probes() -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - depends on host environment
        return {"status": "torch_unavailable", "error": f"{type(exc).__name__}: {exc}"}

    first = torch.arange(8).reshape(2, 4).t()
    first_actual = torch.reshape(first, (4, 2)).flatten()
    first_generated = torch.tensor([0, 2, 4, 6, 1, 3, 5, 7])
    second = torch.arange(6).reshape(2, 3).t()
    second_actual = torch.reshape(second, (6,))
    second_generated = torch.tensor([0, 2, 4, 1, 3, 5])

    indices = torch.tensor([[0, 0, 1, 1], [0, 2, 1, 2]])
    values = torch.tensor([1.0, 2.0, 3.0, 4.0])
    sparse_input = torch.sparse_coo_tensor(indices, values, (2, 3)).coalesce()
    sparse_output = torch.sparse.log_softmax(sparse_input, dim=1).coalesce()
    dense_zero_reference = torch.log_softmax(sparse_input.to_dense(), dim=1)
    explicit_reference_values = torch.cat((
        torch.log_softmax(values[:2], dim=0),
        torch.log_softmax(values[2:], dim=0),
    ))
    explicit_reference = torch.sparse_coo_tensor(
        indices, explicit_reference_values, (2, 3)
    ).coalesce()

    return {
        "status": "completed",
        "reshape": [
            {
                "case": "arange8_transpose_then_reshape",
                "actual_logical_order": first_actual.tolist(),
                "generated_expected_order": first_generated.tolist(),
                "generated_oracle_passes": bool(torch.equal(first_actual, first_generated)),
                "input_flatten_reference_passes": bool(torch.equal(first_actual, first.flatten())),
            },
            {
                "case": "arange6_transpose_then_flat_reshape",
                "actual_logical_order": second_actual.tolist(),
                "generated_expected_order": second_generated.tolist(),
                "generated_oracle_passes": bool(torch.equal(second_actual, second_generated)),
                "input_flatten_reference_passes": bool(torch.equal(second_actual, second.flatten())),
            },
        ],
        "sparse_log_softmax": {
            "output_dense": sparse_output.to_dense().tolist(),
            "dense_zero_reference": dense_zero_reference.tolist(),
            "explicit_sparse_reference": explicit_reference.to_dense().tolist(),
            "generated_dense_zero_reference_passes": bool(
                torch.allclose(sparse_output.to_dense(), dense_zero_reference, atol=1e-6)
            ),
            "explicit_sparse_reference_passes": bool(
                torch.allclose(sparse_output.to_dense(), explicit_reference.to_dense(), atol=1e-6)
            ),
            "explicit_prob_sums": [
                float(torch.exp(explicit_reference_values[:2]).sum()),
                float(torch.exp(explicit_reference_values[2:]).sum()),
            ],
        },
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_signal_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "signal_id", "signal_kind", "source_sha256", "source_record_index", "run_signature",
        "task_id", "baseline", "api", "api_group", "generation_seed", "raw_output_sha256",
        "extracted_code_sha256", "original_exit_code", "anomaly_present", "triage_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(
    input_path: Path,
    documentation_path: Path,
    output_dir: Path,
    replay_apis: set[str],
    timeout_s: float,
    decisions_path: Path | None = None,
) -> dict[str, Any]:
    rows, source_payload = load_jsonl_snapshot(input_path)
    documentation_payload = documentation_path.read_bytes()
    documentation = json.loads(documentation_payload.decode("utf-8"))
    required_docs = ("torch.reshape", "torch.sparse.log_softmax", "torch.sparse.softmax", "torch.compile")
    missing_docs = [name for name in required_docs if name not in documentation]
    if missing_docs:
        raise ValueError(f"documentation snapshot is missing APIs: {missing_docs}")

    source_sha256 = sha256_bytes(source_payload)
    signals = extract_signals(rows, source_sha256)
    ids = [signal["signal_id"] for signal in signals]
    if len(ids) != len(set(ids)):
        raise ValueError("assertion signal IDs are not unique")

    replays = [
        replay_signal(signal, timeout_s)
        for signal in signals
        if str(signal.get("api")) in replay_apis
    ]
    probes = {
        "schema_version": TOOL_VERSION,
        "documentation_sha256": sha256_bytes(documentation_payload),
        "documentation_keys": list(required_docs),
        "local_environment": local_environment(),
        "semantic_probes": semantic_probes(),
        "exact_replays": replays,
        "replay_policy": {
            "requested_apis": sorted(replay_apis),
            "timeout_seconds": timeout_s,
            "same_as_benchmark_environment": False,
            "claim_boundary": "Local replay is diagnostic only; it cannot replace the pinned T4/PyTorch benchmark environment.",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "assertion_signals.jsonl", signals)
    write_signal_csv(output_dir / "assertion_signals.csv", signals)
    write_json(output_dir / "probe_results.json", probes)
    decision_metadata: dict[str, Any]
    if decisions_path is not None:
        decisions, decisions_payload = load_jsonl_snapshot(decisions_path)
        decision_metadata = {
            "path": str(decisions_path),
            "sha256": sha256_bytes(decisions_payload),
            "records": len(decisions),
            **validate_decisions(signals, decisions),
        }
    else:
        decision_metadata = {
            "path": None,
            "sha256": None,
            "records": 0,
            "decision_counts": {},
            "anomaly_counts": {"true": 0, "false": 0, "unknown": len(signals)},
            "provisional_candidate_count": 0,
            "provisional_candidate_ids": [],
            "promoted_count": 0,
            "independent_review_complete": False,
        }
    summary = {
        "schema_version": TOOL_VERSION,
        "input_records": len(rows),
        "benchmark_funnel": benchmark_funnel_counts(rows),
        "assertion_signal_count": len(signals),
        "decision_evidence": decision_metadata,
        "claim_boundary": "Assertion signals are not confirmed framework bugs. Promotion requires audited reproduction, novelty, minimization, and stable/nightly evidence.",
    }
    write_json(output_dir / "triage_summary.json", summary)
    manifest = {
        "schema_version": TOOL_VERSION,
        "tool_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "input_path": str(input_path),
        "input_sha256": source_sha256,
        "input_records": len(rows),
        "documentation_path": str(documentation_path),
        "documentation_sha256": sha256_bytes(documentation_payload),
        "assertion_signal_count": len(signals),
        "signals_by_baseline": dict(sorted(Counter(str(s["baseline"]) for s in signals).items())),
        "signals_by_api": dict(sorted(Counter(str(s["api"]) for s in signals).items())),
        "decision_evidence": decision_metadata,
        "downstream_policy": "All Vn steps remain null until a separate reviewed decision and evidence-bearing workflow update exist.",
        "outputs": [
            "assertion_signals.jsonl", "assertion_signals.csv", "probe_results.json",
            "triage_summary.json",
        ],
    }
    write_json(output_dir / "triage_manifest.json", manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--documentation", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--replay-api", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    manifest = build(
        args.input,
        args.documentation,
        args.output_dir,
        set(args.replay_api),
        args.timeout_seconds,
        args.decisions,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
