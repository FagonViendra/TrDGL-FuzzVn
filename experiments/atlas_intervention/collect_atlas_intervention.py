"""Fail-closed collector for paired Atlas enabled/disabled interventions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED = {
    "schema_version", "experiment_id", "event_id", "evidence_label", "intervention",
    "arm", "unit_id", "generation_seed", "harness_sha256", "model_sha256",
    "decoding_config_sha256", "pair_order", "base_prompt_sha256",
    "effective_prompt_sha256", "candidate_summary_sha256", "atlas_snapshot_sha256",
    "retrieval_performed", "retrieved_cluster_id", "duplicate_decision",
    "duplicate_verified", "duplicate_verification_method",
    "duplicate_verification_artifact_sha256", "rejected_as_duplicate", "atlas_guided",
    "generated_candidate_id", "reproduced", "reproduction_artifact_sha256",
    "unique_signature", "triage_seconds", "status", "error",
}
INTERVENTIONS = {"duplicate_triage", "guided_planning"}
ARMS = {"enabled", "disabled"}
PAIR_ORDERS = {"enabled_first", "disabled_first"}
SHA_FIELDS = {
    "harness_sha256", "model_sha256", "decoding_config_sha256", "base_prompt_sha256",
    "effective_prompt_sha256", "candidate_summary_sha256", "atlas_snapshot_sha256",
    "duplicate_verification_artifact_sha256", "reproduction_artifact_sha256",
    "unique_signature",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    """Prefer portable paths while preserving paths outside the current tree."""
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate(row: dict[str, Any], line_number: int) -> None:
    if set(row) != REQUIRED:
        raise ValueError(f"line {line_number}: fields mismatch: {sorted(set(row) ^ REQUIRED)}")
    if row["schema_version"] != "trdgl_atlas_intervention_event_v2":
        raise ValueError(f"line {line_number}: unknown schema")
    for field in ("experiment_id", "event_id", "unit_id"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"line {line_number}: {field} must be a non-empty string")
    if row["evidence_label"] not in {"validation_only", "campaign"}:
        raise ValueError(f"line {line_number}: invalid evidence label")
    if row["intervention"] not in INTERVENTIONS or row["arm"] not in ARMS:
        raise ValueError(f"line {line_number}: invalid intervention/arm")
    if row["pair_order"] not in PAIR_ORDERS:
        raise ValueError(f"line {line_number}: invalid pair order")
    if not isinstance(row["generation_seed"], int) or isinstance(row["generation_seed"], bool):
        raise ValueError(f"line {line_number}: generation_seed must be an integer")
    for field in ("retrieval_performed", "rejected_as_duplicate", "atlas_guided"):
        if not isinstance(row[field], bool):
            raise ValueError(f"line {line_number}: {field} must be boolean")
    for field in ("duplicate_verified", "reproduced"):
        if row[field] is not None and not isinstance(row[field], bool):
            raise ValueError(f"line {line_number}: {field} must be boolean or null")
    if row["duplicate_decision"] not in {"duplicate", "non_duplicate", "unknown", "not_applicable"}:
        raise ValueError(f"line {line_number}: invalid duplicate decision")
    if row["status"] not in {"complete", "pending", "error"}:
        raise ValueError(f"line {line_number}: invalid status")
    for field in ("retrieved_cluster_id", "duplicate_verification_method", "generated_candidate_id"):
        if row[field] is not None and (not isinstance(row[field], str) or not row[field].strip()):
            raise ValueError(f"line {line_number}: {field} must be a non-empty string or null")
    for field in SHA_FIELDS:
        if row[field] is not None and not _is_sha256(row[field]):
            raise ValueError(f"line {line_number}: {field} is not a lowercase SHA-256")
    if row["status"] == "error" and not row["error"]:
        raise ValueError(f"line {line_number}: error status lacks message")
    if row["status"] != "error" and row["error"] is not None:
        raise ValueError(f"line {line_number}: non-error row has error message")
    if not isinstance(row["triage_seconds"], (int, float)) or isinstance(row["triage_seconds"], bool) or row["triage_seconds"] < 0:
        raise ValueError(f"line {line_number}: triage_seconds must be non-negative")
    if row["arm"] == "disabled":
        if (row["retrieval_performed"] or row["atlas_snapshot_sha256"] is not None
                or row["retrieved_cluster_id"] is not None or row["atlas_guided"]):
            raise ValueError(f"line {line_number}: disabled arm contains Atlas intervention evidence")
        if row["effective_prompt_sha256"] != row["base_prompt_sha256"]:
            raise ValueError(f"line {line_number}: disabled arm changed prompt")
    elif not row["retrieval_performed"] or row["atlas_snapshot_sha256"] is None:
        raise ValueError(f"line {line_number}: enabled arm lacks retrieval/snapshot evidence")

    if row["duplicate_verified"] is None:
        if row["duplicate_verification_method"] is not None or row["duplicate_verification_artifact_sha256"] is not None:
            raise ValueError(f"line {line_number}: unknown duplicate verification has verification evidence")
    elif (not row["duplicate_verification_method"]
          or row["duplicate_verification_artifact_sha256"] is None):
        raise ValueError(f"line {line_number}: known duplicate verification lacks method/artifact")

    if row["intervention"] == "duplicate_triage":
        if row["candidate_summary_sha256"] is None:
            raise ValueError(f"line {line_number}: duplicate triage lacks candidate summary")
        if row["duplicate_decision"] == "not_applicable":
            raise ValueError(f"line {line_number}: duplicate triage lacks a decision")
        if (row["generated_candidate_id"] is not None or row["reproduced"] is not None
                or row["reproduction_artifact_sha256"] is not None
                or row["unique_signature"] is not None or row["atlas_guided"]):
            raise ValueError(f"line {line_number}: duplicate triage contains planning outcome")
        if row["rejected_as_duplicate"] and row["duplicate_decision"] != "duplicate":
            raise ValueError(f"line {line_number}: rejected candidate was not classified duplicate")
        if row["rejected_as_duplicate"] and row["duplicate_verified"] is not True:
            raise ValueError(f"line {line_number}: duplicate rejection lacks positive independent verification")
        if row["duplicate_verified"] is not None and row["duplicate_decision"] != "duplicate":
            raise ValueError(f"line {line_number}: verification attached to non-duplicate decision")
    else:
        if (row["candidate_summary_sha256"] is not None
                or row["duplicate_decision"] != "not_applicable"
                or row["duplicate_verified"] is not None
                or row["duplicate_verification_method"] is not None
                or row["duplicate_verification_artifact_sha256"] is not None
                or row["rejected_as_duplicate"]):
            raise ValueError(f"line {line_number}: planning row contains duplicate-triage outcome")
        if row["status"] == "complete" and row["generated_candidate_id"] is None:
            raise ValueError(f"line {line_number}: completed planning row lacks generated candidate")
        if row["reproduced"] is True and (row["unique_signature"] is None or row["reproduction_artifact_sha256"] is None):
            raise ValueError(f"line {line_number}: reproduced candidate lacks signature/artifact")
        if row["reproduced"] is not True and (row["unique_signature"] is not None or row["reproduction_artifact_sha256"] is not None):
            raise ValueError(f"line {line_number}: non-reproduced candidate has reproduction evidence")
        if row["atlas_guided"] and (row["arm"] != "enabled" or row["retrieved_cluster_id"] is None):
            raise ValueError(f"line {line_number}: guided row lacks enabled-arm cluster evidence")
        prompt_changed = row["effective_prompt_sha256"] != row["base_prompt_sha256"]
        if row["atlas_guided"] != prompt_changed:
            raise ValueError(f"line {line_number}: Atlas-guided flag and effective prompt intervention disagree")


def load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            validate(row, line_number)
            if row["event_id"] in event_ids:
                raise ValueError(f"line {line_number}: duplicate event_id {row['event_id']}")
            event_ids.add(row["event_id"])
            rows.append(row)
    if not rows:
        raise ValueError("empty intervention stream")
    if len({row["experiment_id"] for row in rows}) != 1:
        raise ValueError("multiple experiment IDs")
    if len({row["evidence_label"] for row in rows}) != 1:
        raise ValueError("multiple evidence labels")
    return rows


def _record_count(path: Path, dataset_format: str) -> int:
    if dataset_format == "jsonl":
        with path.open(encoding="utf-8") as handle:
            return sum(bool(line.strip()) for line in handle)
    if dataset_format == "json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("Atlas JSON dataset must be an array")
        return len(value)
    if dataset_format == "csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    raise ValueError(f"unsupported Atlas dataset format: {dataset_format}")


def verify_atlas_source(audit_path: Path, dataset_path: Path | None, manifest_path: Path | None) -> dict[str, Any]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    declared = audit.get("source_audit") or {}
    result: dict[str, Any] = {
        "audit_path": display_path(audit_path),
        "audit_sha256": file_sha256(audit_path),
        "audit_declares_raw_present": bool(declared.get("raw_atlas_dataset_present_in_workspace")),
        "audit_declares_manifest_present": bool(declared.get("independent_manifest_present_in_workspace")),
        "dataset_path": display_path(dataset_path) if dataset_path else None,
        "manifest_path": display_path(manifest_path) if manifest_path else None,
        "raw_atlas_dataset_present": bool(dataset_path and dataset_path.is_file()),
        "independent_manifest_present": bool(manifest_path and manifest_path.is_file()),
        "verified": False,
        "dataset_sha256": None,
        "dataset_bytes": None,
        "record_count": None,
        "snapshot_id": None,
        "verification_errors": [],
    }
    if not result["raw_atlas_dataset_present"] or not result["independent_manifest_present"]:
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        expected = {
            "schema_version", "snapshot_id", "evidence_label", "dataset_file_name",
            "dataset_format", "dataset_sha256", "dataset_bytes", "record_count",
            "created_utc", "created_by", "source_system", "export_command",
        }
        if set(manifest) != expected:
            raise ValueError(f"manifest fields mismatch: {sorted(set(manifest) ^ expected)}")
        if manifest["schema_version"] != "trdgl_atlas_source_manifest_v1":
            raise ValueError("unknown Atlas manifest schema")
        if manifest["evidence_label"] != "campaign":
            raise ValueError("Atlas manifest is not campaign evidence")
        if not all(isinstance(manifest[field], str) and manifest[field].strip() for field in ("snapshot_id", "created_utc", "created_by", "source_system", "export_command")):
            raise ValueError("Atlas manifest provenance fields must be non-empty strings")
        datetime.fromisoformat(manifest["created_utc"].replace("Z", "+00:00"))
        if manifest["dataset_format"] not in {"jsonl", "json", "csv"}:
            raise ValueError("unsupported Atlas dataset format")
        if not _is_sha256(manifest["dataset_sha256"]):
            raise ValueError("Atlas manifest SHA-256 is invalid")
        if not isinstance(manifest["dataset_bytes"], int) or isinstance(manifest["dataset_bytes"], bool) or manifest["dataset_bytes"] < 1:
            raise ValueError("Atlas manifest byte count is invalid")
        if not isinstance(manifest["record_count"], int) or isinstance(manifest["record_count"], bool) or manifest["record_count"] < 1:
            raise ValueError("Atlas manifest record count is invalid")
        if manifest["dataset_file_name"] != dataset_path.name:  # type: ignore[union-attr]
            raise ValueError("Atlas dataset file name differs from manifest")
        computed_hash = file_sha256(dataset_path)  # type: ignore[arg-type]
        computed_bytes = dataset_path.stat().st_size  # type: ignore[union-attr]
        computed_count = _record_count(dataset_path, manifest["dataset_format"])  # type: ignore[arg-type]
        result.update({
            "dataset_sha256": computed_hash,
            "dataset_bytes": computed_bytes,
            "record_count": computed_count,
            "snapshot_id": manifest["snapshot_id"],
        })
        if manifest["dataset_sha256"] != computed_hash:
            raise ValueError("Atlas dataset SHA-256 differs from manifest")
        if manifest["dataset_bytes"] != computed_bytes:
            raise ValueError("Atlas dataset byte count differs from manifest")
        if manifest["record_count"] != computed_count:
            raise ValueError("Atlas dataset record count differs from manifest")
        result["verified"] = True
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        result["verification_errors"].append(str(exc))
    return result


def arm_metrics(rows: list[dict[str, Any]], intervention: str, arm: str) -> dict[str, Any]:
    selected = [row for row in rows if row["intervention"] == intervention and row["arm"] == arm]
    detected = [row for row in selected if row["duplicate_decision"] == "duplicate"]
    known = [row for row in detected if row["duplicate_verified"] is not None]
    reproduced = [row for row in selected if row["reproduced"] is True]
    unique_reproduced = {row["unique_signature"] for row in reproduced}
    triage = [float(row["triage_seconds"]) for row in selected]
    return {
        "events": len(selected),
        "complete": sum(row["status"] == "complete" for row in selected),
        "pending": sum(row["status"] == "pending" for row in selected),
        "error": sum(row["status"] == "error" for row in selected),
        "retrieval_matches": sum(row["retrieved_cluster_id"] is not None for row in selected),
        "duplicates_detected": len(detected),
        "duplicates_rejected": sum(row["rejected_as_duplicate"] for row in selected),
        "duplicate_verification_known": len(known),
        "duplicate_verification_unknown": sum(row["duplicate_verified"] is None for row in detected),
        "retrieval_precision": (sum(row["duplicate_verified"] is True for row in known) / len(known)) if known else None,
        "atlas_guided_candidates": sum(row["atlas_guided"] for row in selected),
        "reproduced_candidates": len(reproduced),
        "unique_reproduced_candidates": len(unique_reproduced),
        "unique_reproduced_per_1000_generations": (len(unique_reproduced) * 1000.0 / len(selected)) if intervention == "guided_planning" and selected else None,
        "triage_seconds_total": sum(triage) if triage else None,
        "triage_seconds_mean": (sum(triage) / len(triage)) if triage else None,
    }


def _paired_effects(pairs: dict[tuple[str, str], dict[str, dict[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for intervention in sorted(INTERVENTIONS):
        complete = [arms for (kind, _), arms in pairs.items() if kind == intervention and set(arms) == ARMS]
        enabled_time = sum(float(arms["enabled"]["triage_seconds"]) for arms in complete)
        disabled_time = sum(float(arms["disabled"]["triage_seconds"]) for arms in complete)
        entry: dict[str, Any] = {
            "complete_pairs": len(complete),
            "enabled_minus_disabled_triage_seconds_mean": ((enabled_time - disabled_time) / len(complete)) if complete else None,
        }
        if intervention == "duplicate_triage":
            entry.update({
                "enabled_only_duplicate_decisions": sum(
                    a["enabled"]["duplicate_decision"] == "duplicate" and a["disabled"]["duplicate_decision"] != "duplicate" for a in complete
                ),
                "enabled_only_duplicate_rejections": sum(
                    a["enabled"]["rejected_as_duplicate"] and not a["disabled"]["rejected_as_duplicate"] for a in complete
                ),
            })
        else:
            entry["enabled_only_reproduced_candidates"] = sum(
                a["enabled"]["reproduced"] is True and a["disabled"]["reproduced"] is not True for a in complete
            )
        result[intervention] = entry
    return result


def summarize(
    events: Path,
    atlas_audit_path: Path,
    required_seeds: list[int],
    atlas_dataset_path: Path | None = None,
    atlas_manifest_path: Path | None = None,
) -> dict[str, Any]:
    rows = load(events)
    atlas_source = verify_atlas_source(atlas_audit_path, atlas_dataset_path, atlas_manifest_path)

    paired: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    duplicate_arm: list[list[str]] = []
    for row in rows:
        key = (row["intervention"], row["unit_id"])
        if row["arm"] in paired[key]:
            duplicate_arm.append([*key, row["arm"]])
        paired[key][row["arm"]] = row
    incomplete_pairs: list[list[str]] = []
    pair_mismatches: list[list[str]] = []
    for key, arms in paired.items():
        if set(arms) != ARMS:
            incomplete_pairs.append(list(key))
            continue
        enabled, disabled = arms["enabled"], arms["disabled"]
        for field in ("generation_seed", "harness_sha256", "model_sha256", "decoding_config_sha256", "base_prompt_sha256", "pair_order"):
            if enabled[field] != disabled[field]:
                pair_mismatches.append([*key, field])
        if key[0] == "duplicate_triage":
            for field in ("candidate_summary_sha256", "effective_prompt_sha256"):
                if enabled[field] != disabled[field]:
                    pair_mismatches.append([*key, field])

    metrics = {
        intervention: {arm: arm_metrics(rows, intervention, arm) for arm in sorted(ARMS)}
        for intervention in sorted(INTERVENTIONS)
    }
    seeds_by_intervention = {
        intervention: sorted({row["generation_seed"] for row in rows if row["intervention"] == intervention})
        for intervention in sorted(INTERVENTIONS)
    }
    harnesses = sorted({row["harness_sha256"] for row in rows})
    models = sorted({row["model_sha256"] for row in rows})
    decoding_configs = sorted({row["decoding_config_sha256"] for row in rows})
    enabled_hashes = sorted({row["atlas_snapshot_sha256"] for row in rows if row["arm"] == "enabled"})
    order_counts = {
        intervention: dict(Counter(
            arms["enabled"]["pair_order"] for (kind, _), arms in paired.items()
            if kind == intervention and set(arms) == ARMS
        )) for intervention in sorted(INTERVENTIONS)
    }
    order_balanced = all(
        abs(counts.get("enabled_first", 0) - counts.get("disabled_first", 0)) <= 1
        for counts in order_counts.values()
    )
    all_complete = all(row["status"] == "complete" for row in rows)
    seeds_complete = all(set(required_seeds).issubset(set(values)) for values in seeds_by_intervention.values())
    both_interventions = all(any(row["intervention"] == intervention for row in rows) for intervention in INTERVENTIONS)
    snapshot_matches = bool(
        atlas_source["verified"] and len(enabled_hashes) == 1
        and enabled_hashes[0] == atlas_source["dataset_sha256"]
    )
    ready = (
        rows[0]["evidence_label"] == "campaign" and atlas_source["verified"]
        and snapshot_matches and both_interventions and not duplicate_arm
        and not incomplete_pairs and not pair_mismatches and len(harnesses) == 1
        and len(models) == 1 and len(decoding_configs) == 1 and order_balanced
        and seeds_complete and all_complete
    )
    blockers: list[str] = []
    if rows[0]["evidence_label"] != "campaign": blockers.append("evidence_label_is_not_campaign")
    if not atlas_source["raw_atlas_dataset_present"]: blockers.append("raw_atlas_dataset_absent")
    if not atlas_source["independent_manifest_present"]: blockers.append("independent_atlas_manifest_absent")
    if atlas_source["raw_atlas_dataset_present"] and atlas_source["independent_manifest_present"] and not atlas_source["verified"]: blockers.append("atlas_source_verification_failed")
    if atlas_source["verified"] and not snapshot_matches: blockers.append("event_snapshot_hash_mismatch")
    if not both_interventions: blockers.append("both_interventions_not_present")
    if duplicate_arm: blockers.append("duplicate_arm_rows")
    if incomplete_pairs: blockers.append("incomplete_pairs")
    if pair_mismatches: blockers.append("pair_contract_mismatches")
    if len(harnesses) != 1: blockers.append("multiple_harnesses")
    if len(models) != 1: blockers.append("multiple_models")
    if len(decoding_configs) != 1: blockers.append("multiple_decoding_configs")
    if not order_balanced: blockers.append("pair_order_imbalanced")
    if not seeds_complete: blockers.append("required_seeds_incomplete")
    if not all_complete: blockers.append("pending_or_error_events")
    return {
        "schema_version": "trdgl_atlas_intervention_summary_v2",
        "evidence_label": rows[0]["evidence_label"],
        "experiment_id": rows[0]["experiment_id"],
        "source": {"events_path": display_path(events), "events_sha256": file_sha256(events), "event_count": len(rows)},
        "atlas_source": {**atlas_source, "enabled_snapshot_hashes": enabled_hashes, "event_snapshot_matches_verified_dataset": snapshot_matches},
        "pairing": {
            "pair_count": len(paired), "duplicate_arm_rows": duplicate_arm,
            "incomplete_pairs": incomplete_pairs, "pair_contract_mismatches": pair_mismatches,
            "single_harness": len(harnesses) == 1,
            "harness_sha256": harnesses[0] if len(harnesses) == 1 else None,
            "single_model": len(models) == 1,
            "model_sha256": models[0] if len(models) == 1 else None,
            "single_decoding_config": len(decoding_configs) == 1,
            "decoding_config_sha256": decoding_configs[0] if len(decoding_configs) == 1 else None,
            "pair_order_counts": order_counts, "pair_order_balanced": order_balanced,
        },
        "required_generation_seeds": required_seeds,
        "observed_seeds_by_intervention": seeds_by_intervention,
        "metrics": metrics,
        "paired_effects": _paired_effects(paired),
        "ready_for_paper_result": ready,
        "blockers": blockers,
        "interpretation": "Retrieval precision excludes unknown duplicate verifications; validation-only and unverified Atlas inputs cannot become paper results.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--atlas-audit", type=Path, required=True)
    parser.add_argument("--atlas-dataset", type=Path)
    parser.add_argument("--atlas-manifest", type=Path)
    parser.add_argument("--required-seeds", default="3407,7711,12011,19001,27103")
    args = parser.parse_args()
    seeds = [int(item.strip()) for item in args.required_seeds.split(",") if item.strip()]
    result = summarize(args.events, args.atlas_audit, seeds, args.atlas_dataset, args.atlas_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "pass", "events": result["source"]["event_count"], "ready_for_paper_result": result["ready_for_paper_result"], "blockers": result["blockers"]}, indent=2))


if __name__ == "__main__":
    main()
