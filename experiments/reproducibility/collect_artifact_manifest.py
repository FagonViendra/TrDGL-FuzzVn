"""Collect a fail-closed TrDGL-FuzzVn reproducibility manifest.

Local-validation mode inventories the collector host and static artifacts only.
It never presents local hardware or missing timing fields as campaign evidence.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import zlib
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COLLECTOR_VERSION = "trdgl_repro_collector_v2"
EXPECTED_BASELINES = ("B0", "B1", "B2", "B3")
PACKAGE_NAMES = ("torch", "llama-cpp-python", "huggingface-hub", "numpy", "pandas")
EXPECTED_RUN_FILES = {
    "run_manifest": "run_manifest.json",
    "raw_events": "events_latest.jsonl",
    "baseline_summary": "baseline_summary.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def display_path(path: Path | None, base: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return resolved.relative_to(base.resolve()).as_posix()
    except ValueError:
        return f"external/{resolved.name}"


def sanitized_command(base: Path) -> list[str]:
    result = [Path(sys.executable).name]
    for token in sys.argv:
        candidate = Path(token)
        if candidate.is_absolute():
            result.append(display_path(candidate, base) or candidate.name)
        else:
            result.append(token)
    return result


def artifact(role: str, path: Path | None, base: Path) -> dict[str, Any]:
    present = bool(path and path.is_file())
    return {
        "role": role,
        "path": display_path(path, base),
        "present": present,
        "size_bytes": path.stat().st_size if present and path else None,
        "sha256": sha256(path) if present and path else None,
        "status": "observed" if present else "pending",
    }


def extract_embedded_benchmark(notebook_path: Path) -> dict[str, Any]:
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assignments: dict[str, Any] = {}
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in {"FROZEN_CANONICAL_SHA256", "MANIFEST_ZLIB_BASE64"}:
                    assignments[name] = ast.literal_eval(node.value)
    encoded = assignments.get("MANIFEST_ZLIB_BASE64")
    expected_hash = assignments.get("FROZEN_CANONICAL_SHA256")
    if not isinstance(encoded, str) or not isinstance(expected_hash, str):
        raise ValueError("notebook lacks the frozen embedded benchmark manifest")
    manifest = json.loads(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual_hash = hashlib.sha256(canonical).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"embedded benchmark hash mismatch: {expected_hash} != {actual_hash}")
    groups = manifest.get("groups") or []
    api_count = sum(len(group.get("apis") or []) for group in groups)
    return {
        "manifest": manifest,
        "sha256": actual_hash,
        "benchmark_id": manifest.get("benchmark_id"),
        "api_count": api_count,
        "api_group_count": len(groups),
        "generation_seeds": manifest.get("generation_seeds") or [],
    }


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def nvidia_driver() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    versions = sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
    return ",".join(versions) or None


def collector_environment() -> dict[str, Any]:
    libraries = package_versions()
    cuda_runtime: str | None = None
    cuda_available: bool | None = None
    gpus: list[dict[str, Any]] = []
    try:
        import torch  # type: ignore

        cuda_runtime = torch.version.cuda
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                gpus.append({
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "memory_bytes": int(properties.total_memory),
                })
    except Exception:
        cuda_available = None
    return {
        "status": "observed",
        "scope": "collector_host",
        "os": platform.platform(),
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "libraries": libraries,
        "cuda_runtime": cuda_runtime,
        "cuda_available": cuda_available,
        "driver_version": nvidia_driver(),
        "gpus": gpus,
    }


def campaign_environment(run_manifest: dict[str, Any]) -> dict[str, Any]:
    gpu = run_manifest.get("gpu")
    libraries = {name: None for name in PACKAGE_NAMES}
    libraries["torch"] = run_manifest.get("torch_version")
    for name, version in (run_manifest.get("packages") or {}).items():
        libraries[name] = version
    return {
        "status": "observed",
        "scope": "campaign_run",
        "os": run_manifest.get("os"),
        "python": {"version": run_manifest.get("python"), "implementation": run_manifest.get("python_implementation")},
        "libraries": libraries,
        "cuda_runtime": run_manifest.get("torch_cuda"),
        "cuda_available": True if gpu else None,
        "driver_version": run_manifest.get("driver_version"),
        "gpus": [{"index": 0, "name": gpu, "memory_bytes": run_manifest.get("gpu_memory_bytes")}] if gpu else [],
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: event is not an object")
            rows.append(row)
    return rows


def collect_run(run_dir: Path | None, base: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    if run_dir is None:
        empty = artifact("run_manifest", None, base)
        return {
            "status": "pending",
            "run_manifest": empty,
            "run_signature": None,
            "generation_seeds": [],
            "benchmark_id": None,
            "benchmark_manifest_sha256": None,
            "documentation_sha256": None,
            "models": {"base": None, "tuned": None},
            "decoding": None,
            "subprocess_timeout_seconds": None,
            "execution_command": None,
            "counts": {
                "selected_tasks": None, "expected_events": None, "generation_events": None,
                "identified_unique_events": None, "duplicate_identity_events": None,
                "missing_identity_events": None, "baseline_unique_events": None,
                "executed_tests": None, "selected_task_matrix_complete": None,
                "full_benchmark_complete": None,
            },
            "timing": {"status": "pending", "basis": None, "started_at_utc": None, "ended_at_utc": None, "duration_seconds": None, "generation_seconds_sum": None, "subprocess_seconds_sum": None},
            "throughput": {"status": "pending", "generations_per_hour": None, "executed_tests_per_hour": None},
            "resources": {"status": "pending", "gpu_hours": None, "cpu_hours": None, "peak_vram_bytes": None},
        }, [empty, artifact("raw_events", None, base), artifact("baseline_summary", None, base)], None

    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    events_path = run_dir / "events_latest.jsonl"
    if not events_path.is_file() and (run_dir / "events.jsonl").is_file():
        events_path = run_dir / "events.jsonl"
    summary_path = run_dir / "baseline_summary.csv"
    artifacts = [
        artifact("run_manifest", manifest_path, base),
        artifact("raw_events", events_path, base),
        artifact("baseline_summary", summary_path, base),
    ]
    if not manifest_path.is_file():
        raise FileNotFoundError(f"campaign mode requires {manifest_path}")
    run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = load_jsonl(events_path) if events_path.is_file() else []
    manifest_signature = run_manifest.get("run_signature")
    if not isinstance(manifest_signature, str) or not manifest_signature:
        raise ValueError("campaign run manifest lacks run_signature")
    signatures = {row.get("run_signature") for row in rows}
    if rows and signatures != {manifest_signature}:
        raise ValueError("event stream and run manifest do not share one run signature")

    starts = [parse_utc(row["started_utc"]) for row in rows if row.get("started_utc")]
    ends = [parse_utc(row["finished_utc"]) for row in rows if row.get("finished_utc")]
    duration = (max(ends) - min(starts)).total_seconds() if starts and ends else None
    executed_tests = sum(row.get("exit_code") is not None or bool(row.get("timeout")) for row in rows)
    generation_seconds = sum(float(row["generation_seconds"]) for row in rows if row.get("generation_seconds") is not None)
    subprocess_seconds = sum(float(row["subprocess_seconds"]) for row in rows if row.get("subprocess_seconds") is not None)
    seeds = sorted({int(row["generation_seed"]) for row in rows if row.get("generation_seed") is not None})
    selected_tasks = run_manifest.get("selected_task_count")
    expected_events = int(selected_tasks) * 4 if isinstance(selected_tasks, int) else None
    identities = [
        (str(row["baseline"]), str(row["task_id"]))
        for row in rows
        if row.get("baseline") not in (None, "") and row.get("task_id") not in (None, "")
    ]
    unique_identities = set(identities)
    missing_identity_events = len(rows) - len(identities)
    duplicate_identity_events = len(identities) - len(unique_identities)
    baseline_unique_events = {
        baseline: sum(identity[0] == baseline for identity in unique_identities)
        for baseline in EXPECTED_BASELINES
    }
    complete = (
        len(rows) == expected_events
        and len(unique_identities) == expected_events
        and missing_identity_events == 0
        and duplicate_identity_events == 0
        and all(baseline_unique_events[baseline] == int(selected_tasks) for baseline in EXPECTED_BASELINES)
    ) if expected_events is not None else None
    throughput_status = "observed" if duration is not None and duration > 0 else "pending"
    timing_status = "observed" if duration is not None else "pending"

    run = {
        "status": "observed",
        "run_manifest": artifacts[0],
        "run_signature": manifest_signature,
        "generation_seeds": seeds,
        "benchmark_id": run_manifest.get("benchmark_id"),
        "benchmark_manifest_sha256": run_manifest.get("manifest_sha256"),
        "documentation_sha256": run_manifest.get("documentation_sha256"),
        "models": {
            "base": run_manifest.get("base_model"),
            "tuned": run_manifest.get("tuned_model"),
        },
        "decoding": run_manifest.get("decoding"),
        "subprocess_timeout_seconds": run_manifest.get("subprocess_timeout_s"),
        "execution_command": run_manifest.get("execution_command"),
        "counts": {
            "selected_tasks": selected_tasks,
            "expected_events": expected_events,
            "generation_events": len(rows) if events_path.is_file() else None,
            "identified_unique_events": len(unique_identities) if events_path.is_file() else None,
            "duplicate_identity_events": duplicate_identity_events if events_path.is_file() else None,
            "missing_identity_events": missing_identity_events if events_path.is_file() else None,
            "baseline_unique_events": baseline_unique_events if events_path.is_file() else None,
            "executed_tests": executed_tests if events_path.is_file() else None,
            "selected_task_matrix_complete": complete,
            "full_benchmark_complete": None,
        },
        "timing": {
            "status": timing_status,
            "basis": "event_span_excludes_pre_first-event_setup" if duration is not None else None,
            "started_at_utc": min(starts).isoformat() if starts else None,
            "ended_at_utc": max(ends).isoformat() if ends else None,
            "duration_seconds": duration,
            "generation_seconds_sum": generation_seconds if rows else None,
            "subprocess_seconds_sum": subprocess_seconds if rows else None,
        },
        "throughput": {
            "status": throughput_status,
            "generations_per_hour": len(rows) * 3600.0 / duration if duration and duration > 0 else None,
            "executed_tests_per_hour": executed_tests * 3600.0 / duration if duration and duration > 0 else None,
        },
        "resources": {
            "status": "observed" if any(run_manifest.get(key) is not None for key in ("gpu_hours", "cpu_hours", "peak_vram_bytes")) else "pending",
            "gpu_hours": run_manifest.get("gpu_hours"),
            "cpu_hours": run_manifest.get("cpu_hours"),
            "peak_vram_bytes": run_manifest.get("peak_vram_bytes"),
        },
    }
    return run, artifacts, run_manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "schema_version", "evidence_label", "collection", "source_scope", "environment",
        "benchmark", "run", "release", "artifacts", "completeness",
    }
    if set(manifest) != required:
        raise ValueError(f"top-level keys mismatch: {sorted(set(manifest) ^ required)}")
    if manifest["schema_version"] != "trdgl_artifact_manifest_v2":
        raise ValueError("unknown schema version")
    if manifest["evidence_label"] == "local_validation":
        run = manifest["run"]
        for path in ("run_signature",):
            if run[path] is not None:
                raise ValueError(f"local validation cannot claim {path}")
        if any(run["timing"][key] is not None for key in ("started_at_utc", "ended_at_utc", "duration_seconds")):
            raise ValueError("local validation cannot claim campaign timing")
        if any(run["throughput"][key] is not None for key in ("generations_per_hour", "executed_tests_per_hour")):
            raise ValueError("local validation cannot claim campaign throughput")
    counts = manifest["run"]["counts"]
    if counts["generation_events"] is not None:
        components = (
            counts["identified_unique_events"], counts["duplicate_identity_events"],
            counts["missing_identity_events"],
        )
        if any(value is None for value in components):
            raise ValueError("observed generation count lacks identity audit")
        if counts["generation_events"] != sum(components):
            raise ValueError("generation identity counts do not sum to raw events")
        if counts["baseline_unique_events"] is None:
            raise ValueError("observed generation count lacks baseline audit")
    for item in manifest["artifacts"]:
        if item["present"]:
            if item["sha256"] is None or item["size_bytes"] is None or item["status"] != "observed":
                raise ValueError(f"present artifact lacks evidence: {item['role']}")
        elif item["sha256"] is not None or item["size_bytes"] is not None:
            raise ValueError(f"missing artifact has fabricated hash/size: {item['role']}")


def collect(args: argparse.Namespace) -> dict[str, Any]:
    base = args.workspace_root.resolve()
    notebook_path = args.notebook.resolve()
    embedded = extract_embedded_benchmark(notebook_path)
    run, run_artifacts, run_manifest = collect_run(args.run_dir, base)
    mode = args.mode
    if mode == "campaign" and run_manifest is None:
        raise ValueError("campaign mode requires --run-dir")
    if run_manifest is not None:
        recorded_benchmark_id = run_manifest.get("benchmark_id")
        recorded_manifest_hash = run_manifest.get("manifest_sha256")
        if recorded_benchmark_id is not None and recorded_benchmark_id != embedded["benchmark_id"]:
            raise ValueError("run manifest benchmark_id does not match frozen notebook")
        if recorded_manifest_hash is not None and recorded_manifest_hash != embedded["sha256"]:
            raise ValueError("run manifest benchmark hash does not match frozen notebook")
    environment = campaign_environment(run_manifest) if mode == "campaign" else collector_environment()
    if run["counts"]["generation_events"] is not None:
        full_event_count = embedded["api_count"] * len(embedded["generation_seeds"]) * 4
        run["counts"]["full_benchmark_complete"] = (
            run["counts"]["generation_events"] == full_event_count
            and run["counts"]["identified_unique_events"] == full_event_count
            and run["counts"]["duplicate_identity_events"] == 0
            and run["counts"]["missing_identity_events"] == 0
            and run["counts"]["baseline_unique_events"] == {
                baseline: embedded["api_count"] * len(embedded["generation_seeds"])
                for baseline in EXPECTED_BASELINES
            }
            and run["generation_seeds"] == embedded["generation_seeds"]
        )
    notebook_artifact = artifact("benchmark_notebook", notebook_path, base)
    environment_lock = artifact("environment_lock", args.environment_lock, base)
    artifacts = [notebook_artifact, *run_artifacts, environment_lock]
    for extra in args.artifact:
        artifacts.append(artifact("additional_artifact", extra.resolve(), base))

    missing_fields: list[str] = []
    if run["run_signature"] is None: missing_fields.append("run.run_signature")
    for field in (
        "benchmark_id", "benchmark_manifest_sha256", "documentation_sha256", "decoding",
        "subprocess_timeout_seconds", "execution_command",
    ):
        if run[field] in (None, "", {}): missing_fields.append(f"run.{field}")
    for role, model in run["models"].items():
        required_model_fields = ("repo_id", "filename", "revision", "file_sha256", "file_size")
        if not isinstance(model, dict) or any(model.get(field) in (None, "") for field in required_model_fields):
            missing_fields.append(f"run.models.{role}")
    if run["counts"]["generation_events"] is None: missing_fields.append("run.counts.generation_events")
    if run["counts"]["full_benchmark_complete"] is not True: missing_fields.append("run.counts.full_benchmark_complete")
    if run["counts"]["duplicate_identity_events"] not in (None, 0): missing_fields.append("run.counts.identity_integrity")
    if run["counts"]["missing_identity_events"] not in (None, 0): missing_fields.append("run.counts.identity_integrity")
    if run["timing"]["duration_seconds"] is None: missing_fields.append("run.timing.duration_seconds")
    if run["throughput"]["generations_per_hour"] is None: missing_fields.append("run.throughput.generations_per_hour")
    if run["resources"]["gpu_hours"] is None: missing_fields.append("run.resources.gpu_hours")
    if run["resources"]["cpu_hours"] is None: missing_fields.append("run.resources.cpu_hours")
    if environment["driver_version"] is None: missing_fields.append("environment.driver_version")
    if environment["os"] is None: missing_fields.append("environment.os")
    if environment["python"]["version"] is None: missing_fields.append("environment.python.version")
    if environment["libraries"].get("torch") is None: missing_fields.append("environment.libraries.torch")
    for item in artifacts:
        if not item["present"] and item["role"] != "environment_lock":
            missing_fields.append(f"artifacts.{item['role']}")
    if not environment_lock["present"]: missing_fields.append("release.environment_lock")
    if not args.public_artifact_url_or_doi: missing_fields.append("release.public_artifact_url_or_doi")
    missing_fields = sorted(set(missing_fields))

    manifest = {
        "schema_version": "trdgl_artifact_manifest_v2",
        "evidence_label": mode,
        "collection": {
            "collector_version": COLLECTOR_VERSION,
            "collected_at_utc": utc_now(),
            "path_base": "workspace_root",
            "exact_command": sanitized_command(base),
        },
        "source_scope": {
            "mode": mode,
            "run_environment_observed": mode == "campaign",
            "claim_boundaries": [
                "local_validation describes the collector host, not the Colab campaign runtime" if mode == "local_validation" else "campaign fields are copied or deterministically aggregated from the supplied run directory",
                "null and pending mean not evidenced; they are never interpreted as zero",
                "event-span throughput excludes setup before the first persisted event",
            ],
        },
        "environment": environment,
        "benchmark": {
            "notebook": notebook_artifact,
            "embedded_manifest_sha256": embedded["sha256"],
            "benchmark_id": embedded["benchmark_id"],
            "api_count": embedded["api_count"],
            "api_group_count": embedded["api_group_count"],
            "generation_seeds": embedded["generation_seeds"],
        },
        "run": run,
        "release": {
            "environment_lock": environment_lock,
            "public_artifact_url_or_doi": args.public_artifact_url_or_doi,
        },
        "artifacts": artifacts,
        "completeness": {
            "status": "observed" if not missing_fields else "pending",
            "ready_for_release": not missing_fields,
            "missing_fields": missing_fields,
        },
    }
    validate_manifest(manifest)
    return manifest


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[3]
    paper = Path(__file__).resolve().parents[2]
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mode", choices=("local_validation", "campaign"), default="local_validation")
    result.add_argument("--workspace-root", type=Path, default=root)
    result.add_argument("--notebook", type=Path, default=paper / "experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb")
    result.add_argument("--run-dir", type=Path)
    result.add_argument("--environment-lock", type=Path)
    result.add_argument("--public-artifact-url-or-doi")
    result.add_argument("--artifact", type=Path, action="append", default=[])
    result.add_argument("--output", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    manifest = collect(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "pass",
        "output": str(args.output),
        "evidence_label": manifest["evidence_label"],
        "ready_for_release": manifest["completeness"]["ready_for_release"],
        "missing_fields": len(manifest["completeness"]["missing_fields"]),
    }, indent=2))


if __name__ == "__main__":
    main()
