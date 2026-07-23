"""Aggregate independently checkpointed seed shards under a verified common contract."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import collect_benchmark_results as results


INDEX_FIELDS = {"schema_version", "evidence_label", "benchmark_id", "shards"}
SHARD_FIELDS = {"generation_seed", "run_signature", "events_path", "run_manifest_path", "executed_notebook_path"}
VOLATILE_MANIFEST_FIELDS = {"created_utc", "run_signature", "event_log", "selected_task_count"}
REQUIRED_MANIFEST_FIELDS = {
    "created_utc", "benchmark_id", "manifest_sha256", "documentation_sha256", "torch_version",
    "torch_cuda", "python", "packages", "gpu", "base_model", "tuned_model",
    "decoding", "subprocess_timeout_s", "selected_task_count", "run_signature", "event_log",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def notebook_contract(path: Path) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    code_sources = ["".join(cell.get("source", [])) for cell in document.get("cells", []) if cell.get("cell_type") == "code"]
    if not code_sources:
        raise ValueError(f"notebook has no code cells: {path}")
    runner_versions: list[str] = []
    for source in code_sources:
        tree = ast.parse(source)
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "RUNNER_VERSION"):
                runner_versions.append(ast.literal_eval(node.value))
    if len(runner_versions) != 1 or not isinstance(runner_versions[0], str):
        raise ValueError(f"notebook must contain exactly one literal RUNNER_VERSION: {path}")
    return {
        "code_source_sha256": canonical_hash(code_sources),
        "runner_version": runner_versions[0],
    }


def frozen_run_contract(path: Path) -> dict[str, Any]:
    """Extract the paper-critical literal configuration from the frozen notebook.

    Cross-shard equality alone is insufficient: five shards can be mutually
    identical while all using the wrong model or decoding contract.  Keep this
    extraction deliberately narrow and fail if the notebook stops expressing
    these settings as auditable literals.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    wanted = {
        "BASE_MODEL", "TUNED_MODEL", "TEMPERATURE", "TOP_P", "TOP_K",
        "MIN_P", "REPEAT_PENALTY", "SUBPROCESS_TIMEOUT_S",
    }
    values: dict[str, Any] = {}
    max_tokens_default: int | None = None
    for cell in document.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        tree = ast.parse("".join(cell.get("source", [])))
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            name = node.targets[0].id
            if name in wanted:
                try:
                    values[name] = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"frozen notebook {name} must be a literal") from exc
            elif name == "MAX_TOKENS":
                # Expected form: int(os.environ.get('TRDGL_MAX_TOKENS', '600')).
                call = node.value
                if (isinstance(call, ast.Call) and len(call.args) == 1
                        and isinstance(call.args[0], ast.Call)
                        and len(call.args[0].args) >= 2):
                    try:
                        max_tokens_default = int(ast.literal_eval(call.args[0].args[1]))
                    except (ValueError, TypeError):
                        pass
    missing = wanted - set(values)
    if missing or max_tokens_default is None:
        raise ValueError(f"frozen notebook run contract is not statically auditable: {sorted(missing)}")
    return {
        "base_model": values["BASE_MODEL"],
        "tuned_model": values["TUNED_MODEL"],
        "decoding": {
            "temperature": values["TEMPERATURE"],
            "top_p": values["TOP_P"],
            "top_k": values["TOP_K"],
            "min_p": values["MIN_P"],
            "repeat_penalty": values["REPEAT_PENALTY"],
            "max_tokens": max_tokens_default,
        },
        "subprocess_timeout_s": values["SUBPROCESS_TIMEOUT_S"],
    }


def resolve(index_path: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else index_path.parent / candidate


def load_index(index_path: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if set(index) != INDEX_FIELDS:
        raise ValueError(f"campaign index fields mismatch: {sorted(set(index) ^ INDEX_FIELDS)}")
    if index["schema_version"] != "trdgl_campaign_shard_index_v1":
        raise ValueError("unknown campaign shard index schema")
    if index["evidence_label"] not in {"validation_only", "campaign"}:
        raise ValueError("invalid campaign shard evidence label")
    if not isinstance(index["shards"], list) or not index["shards"]:
        raise ValueError("campaign shard index is empty")
    for number, shard in enumerate(index["shards"], 1):
        if not isinstance(shard, dict) or set(shard) != SHARD_FIELDS:
            raise ValueError(f"shard {number}: fields mismatch")
        if not isinstance(shard["generation_seed"], int) or isinstance(shard["generation_seed"], bool):
            raise ValueError(f"shard {number}: invalid generation seed")
        if not results.is_sha256(shard["run_signature"]):
            raise ValueError(f"shard {number}: invalid run signature")
        for field in ("events_path", "run_manifest_path", "executed_notebook_path"):
            if not isinstance(shard[field], str) or not shard[field].strip():
                raise ValueError(f"shard {number}: invalid {field}")
    signatures = [shard["run_signature"] for shard in index["shards"]]
    if len(signatures) != len(set(signatures)):
        raise ValueError("duplicate run signature in campaign index")
    return index


def collect_shards(index_path: Path, frozen_notebook: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    index = load_index(index_path)
    frozen_manifest, frozen_manifest_hash = results.load_frozen_manifest(frozen_notebook)
    if index["benchmark_id"] != frozen_manifest["benchmark_id"]:
        raise ValueError("campaign index benchmark ID mismatch")
    expected_seeds = list(frozen_manifest["generation_seeds"])
    declared_seeds = [shard["generation_seed"] for shard in index["shards"]]
    if len(declared_seeds) != len(set(declared_seeds)):
        raise ValueError("duplicate generation seed in campaign index")
    if not set(declared_seeds).issubset(set(expected_seeds)):
        raise ValueError("unexpected generation seed in campaign index")

    frozen_contract = notebook_contract(frozen_notebook)
    frozen_configuration = frozen_run_contract(frozen_notebook)
    normalized_manifests: list[dict[str, Any]] = []
    combined: list[dict[str, Any]] = []
    shard_reports: list[dict[str, Any]] = []
    for shard in index["shards"]:
        events_path = resolve(index_path, shard["events_path"])
        manifest_path = resolve(index_path, shard["run_manifest_path"])
        executed_notebook = resolve(index_path, shard["executed_notebook_path"])
        for path in (events_path, manifest_path, executed_notebook):
            if not path.is_file():
                raise ValueError(f"shard artifact is missing: {path}")
        executed_contract = notebook_contract(executed_notebook)
        if executed_contract != frozen_contract:
            raise ValueError(f"seed {shard['generation_seed']}: executed notebook code/runner differs from frozen notebook")

        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing_manifest = REQUIRED_MANIFEST_FIELDS - set(run_manifest)
        if missing_manifest:
            raise ValueError(f"seed {shard['generation_seed']}: run manifest misses {sorted(missing_manifest)}")
        try:
            created = datetime.fromisoformat(run_manifest["created_utc"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise ValueError("timestamp has no timezone")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"seed {shard['generation_seed']}: invalid manifest creation timestamp") from exc
        for field in ("manifest_sha256", "documentation_sha256", "run_signature"):
            if not results.is_sha256(run_manifest[field]):
                raise ValueError(f"seed {shard['generation_seed']}: invalid manifest {field}")
        for field in ("benchmark_id", "torch_version", "torch_cuda", "python", "gpu", "event_log"):
            if not isinstance(run_manifest[field], str) or not run_manifest[field].strip():
                raise ValueError(f"seed {shard['generation_seed']}: invalid manifest {field}")
        if not isinstance(run_manifest["packages"], dict) or not run_manifest["packages"]:
            raise ValueError(f"seed {shard['generation_seed']}: package inventory is empty")
        if any(
            not isinstance(name, str) or not name.strip()
            or not isinstance(version, str) or not version.strip()
            for name, version in run_manifest["packages"].items()
        ):
            raise ValueError(f"seed {shard['generation_seed']}: package inventory has invalid entries")
        if run_manifest["run_signature"] != shard["run_signature"]:
            raise ValueError(f"seed {shard['generation_seed']}: manifest/index signature mismatch")
        if run_manifest["benchmark_id"] != frozen_manifest["benchmark_id"] or run_manifest["manifest_sha256"] != frozen_manifest_hash:
            raise ValueError(f"seed {shard['generation_seed']}: frozen benchmark identity mismatch")
        if run_manifest["selected_task_count"] != frozen_manifest["target_api_count"]:
            raise ValueError(f"seed {shard['generation_seed']}: selected task count is not 120")
        for field, expected in frozen_configuration.items():
            if run_manifest[field] != expected:
                raise ValueError(
                    f"seed {shard['generation_seed']}: run manifest {field} differs from frozen notebook"
                )
        normalized = {key: value for key, value in run_manifest.items() if key not in VOLATILE_MANIFEST_FIELDS}
        normalized_manifests.append(normalized)

        rows, stream = results.load_events(events_path, shard["run_signature"])
        if {row["generation_seed"] for row in rows} != {shard["generation_seed"]}:
            raise ValueError(f"seed {shard['generation_seed']}: event stream contains another seed")
        expected_task_ids = {
            task_id for task_id, task in results.expected_tasks(frozen_manifest).items()
            if task["generation_seed"] == shard["generation_seed"]
        }
        observed_task_ids = {row["task_id"] for row in rows}
        if not observed_task_ids.issubset(expected_task_ids):
            raise ValueError(f"seed {shard['generation_seed']}: event stream contains unexpected API/task")
        expected_events = frozen_manifest["target_api_count"] * len(frozen_manifest["baseline_ids"])
        complete = len(rows) == expected_events and len(observed_task_ids) == frozen_manifest["target_api_count"]
        combined.extend(rows)
        shard_reports.append({
            "generation_seed": shard["generation_seed"],
            "run_signature": shard["run_signature"],
            "events_sha256": stream["events_sha256"],
            "run_manifest_sha256": results.sha256_file(manifest_path),
            "executed_notebook_sha256": results.sha256_file(executed_notebook),
            "notebook_code_source_sha256": executed_contract["code_source_sha256"],
            "runner_version": executed_contract["runner_version"],
            "observed_events": len(rows),
            "expected_events": expected_events,
            "complete": complete,
        })

    config_hashes = {canonical_hash(manifest) for manifest in normalized_manifests}
    if len(config_hashes) != 1:
        raise ValueError("normalized shard run manifests differ (environment/model/decoding/harness drift)")
    return combined, {
        "index": index,
        "index_sha256": results.sha256_file(index_path),
        "frozen_notebook_sha256": results.sha256_file(frozen_notebook),
        "notebook_code_source_sha256": frozen_contract["code_source_sha256"],
        "runner_version": frozen_contract["runner_version"],
        "normalized_configuration_sha256": next(iter(config_hashes)),
        "frozen_run_contract_sha256": canonical_hash(frozen_configuration),
        "expected_seeds": expected_seeds,
        "declared_seeds": declared_seeds,
        "all_run_signatures_distinct": len({shard["run_signature"] for shard in index["shards"]}) == len(index["shards"]),
        "all_seeds_present": set(declared_seeds) == set(expected_seeds),
        "all_shards_complete": all(report["complete"] for report in shard_reports),
        "shards": shard_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--cells-csv", type=Path, required=True)
    parser.add_argument("--coverage-csv", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--combined-events", type=Path, required=True)
    args = parser.parse_args()

    rows, campaign = collect_shards(args.index, args.notebook)
    args.combined_events.parent.mkdir(parents=True, exist_ok=True)
    args.combined_events.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    summary, cells = results.summarize(
        args.combined_events, args.notebook, campaign["index"]["evidence_label"],
        allow_multiple_signatures=True, configuration_equivalence_verified=True,
    )
    summary["campaign_shards"] = campaign
    if not campaign["all_seeds_present"]:
        summary["blockers"].append("campaign_seed_shards_missing")
    if not campaign["all_shards_complete"]:
        summary["blockers"].append("campaign_seed_shards_incomplete")
    summary["full_benchmark_complete"] = summary["full_benchmark_complete"] and campaign["all_seeds_present"] and campaign["all_shards_complete"]
    summary["ready_for_paper_result"] = summary["evidence_label"] == "campaign" and summary["full_benchmark_complete"] and not summary["blockers"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results.write_cells(args.cells_csv, cells)
    results.write_cells(args.coverage_csv, results.build_coverage_rows(args.notebook, args.combined_events, allow_multiple_signatures=True))
    if args.report_md:
        results.write_markdown(args.report_md, summary)
    print(json.dumps({
        "observed": len(rows), "expected": summary["benchmark"]["expected_event_count"],
        "shards": len(campaign["shards"]), "complete": summary["full_benchmark_complete"],
        "ready": summary["ready_for_paper_result"], "blockers": summary["blockers"],
    }, indent=2))


if __name__ == "__main__":
    main()
