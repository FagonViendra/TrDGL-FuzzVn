"""Audit a live seed checkpoint without upgrading notebook logs to raw evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import collect_benchmark_campaign as campaign
import collect_benchmark_results as results


COMPLETION_RE = re.compile(r"Runner finished\. Events for this signature:\s*(\d+)\s*/\s*(\d+)")


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def transcript_completion(path: Path) -> dict[str, int] | None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    matches: list[tuple[int, int]] = []
    for cell in notebook.get("cells", []):
        for output in cell.get("outputs", []):
            text = output.get("text", "")
            value = "".join(text) if isinstance(text, list) else str(text)
            matches.extend((int(a), int(b)) for a, b in COMPLETION_RE.findall(value))
    if not matches:
        return None
    observed, expected = matches[-1]
    return {"observed_events": observed, "expected_events": expected}


def audit(
    events_path: Path,
    run_manifest_path: Path,
    frozen_notebook: Path,
    executed_notebook: Path,
    run_signature: str,
) -> dict[str, Any]:
    frozen_manifest, frozen_hash = results.load_frozen_manifest(frozen_notebook)
    rows, stream = results.load_events(events_path, run_signature)
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))

    contract_errors: list[str] = []
    if campaign.notebook_contract(executed_notebook) != campaign.notebook_contract(frozen_notebook):
        contract_errors.append("executed_notebook_code_differs_from_frozen_notebook")
    if run_manifest.get("run_signature") != run_signature:
        contract_errors.append("run_manifest_signature_mismatch")
    if run_manifest.get("benchmark_id") != frozen_manifest["benchmark_id"]:
        contract_errors.append("run_manifest_benchmark_id_mismatch")
    if run_manifest.get("manifest_sha256") != frozen_hash:
        contract_errors.append("run_manifest_frozen_manifest_hash_mismatch")
    if run_manifest.get("selected_task_count") != frozen_manifest["target_api_count"]:
        contract_errors.append("run_manifest_selected_task_count_mismatch")
    frozen_configuration = campaign.frozen_run_contract(frozen_notebook)
    for field, expected in frozen_configuration.items():
        if run_manifest.get(field) != expected:
            contract_errors.append(f"run_manifest_{field}_mismatch")

    observed_seeds = sorted({row["generation_seed"] for row in rows})
    if len(observed_seeds) != 1:
        contract_errors.append("raw_stream_does_not_contain_exactly_one_seed")
    elif observed_seeds[0] not in frozen_manifest["generation_seeds"]:
        contract_errors.append("raw_stream_seed_is_not_frozen")

    expected_events = frozen_manifest["target_api_count"] * len(frozen_manifest["baseline_ids"])
    transcript = transcript_completion(executed_notebook)
    transcript_matches_raw = transcript is None or transcript["observed_events"] == len(rows)
    blockers: list[str] = []
    if contract_errors:
        blockers.append("checkpoint_contract_errors")
    if len(rows) != expected_events:
        blockers.append("persisted_seed_events_incomplete")
    if not transcript_matches_raw:
        blockers.append("executed_notebook_transcript_differs_from_persisted_raw_stream")

    return {
        "schema_version": "trdgl_checkpoint_provenance_audit_v1",
        "evidence_label": "validation_only",
        "artifacts": {
            "events_path": display_path(events_path),
            "events_sha256": stream["events_sha256"],
            "run_manifest_path": display_path(run_manifest_path),
            "run_manifest_sha256": results.sha256_file(run_manifest_path),
            "frozen_notebook_path": display_path(frozen_notebook),
            "frozen_notebook_sha256": results.sha256_file(frozen_notebook),
            "executed_notebook_path": display_path(executed_notebook),
            "executed_notebook_sha256": results.sha256_file(executed_notebook),
        },
        "run_signature": run_signature,
        "generation_seeds": observed_seeds,
        "persisted_raw_event_count": len(rows),
        "persisted_baseline_counts": {
            baseline: sum(row["baseline"] == baseline for row in rows)
            for baseline in results.BASELINES
        },
        "expected_seed_event_count": expected_events,
        "persisted_seed_completion_rate": len(rows) / expected_events,
        "executed_notebook_transcript": transcript,
        "transcript_matches_persisted_raw_stream": transcript_matches_raw,
        "paper_evidence_event_count": len(rows),
        "paper_evidence_rule": "Only validated persisted JSONL rows count; notebook stdout is provenance, not a substitute for raw events.",
        "contract_errors": contract_errors,
        "ready_for_campaign_index": not blockers,
        "blockers": blockers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("run_manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--executed-notebook", type=Path, required=True)
    parser.add_argument("--run-signature", required=True)
    args = parser.parse_args()
    report = audit(
        args.events, args.run_manifest, args.notebook, args.executed_notebook,
        args.run_signature,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "persisted": report["persisted_raw_event_count"],
        "expected": report["expected_seed_event_count"],
        "ready": report["ready_for_campaign_index"],
        "blockers": report["blockers"],
    }, indent=2))


if __name__ == "__main__":
    main()
