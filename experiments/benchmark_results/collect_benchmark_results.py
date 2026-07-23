"""Collect fail-closed coverage and fairness metrics from append-only benchmark events."""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import json
import math
import zlib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


BASELINES = ("B0", "B1", "B2", "B3")
AB_ORDERS = {"B2_then_B3", "B3_then_B2"}
BOOL_METRICS = ("parseable", "ast_pass", "runnable", "target_valid", "oracle_bearing")
REQUIRED_EVENT_FIELDS = {
    "run_signature", "started_utc", "finished_utc", "baseline", "model", "task_id",
    "api", "api_group", "api_index", "generation_seed", "ab_order",
    "logical_baseline_order", "prompt_sha256", "raw_output_sha256", "raw_generation",
    "generation_seconds", "seed_backend", "parseable", "ast_pass",
    "target_call_present", "oracle_present", "fake_assertion", "subprocess_seconds",
    "runnable", "target_valid", "oracle_bearing",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed


def load_frozen_manifest(notebook: Path) -> tuple[dict[str, Any], str]:
    document = json.loads(notebook.read_text(encoding="utf-8"))
    assignments: dict[str, str] = {}
    for cell in document.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        tree = ast.parse("".join(cell.get("source", [])))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            if name in {"FROZEN_CANONICAL_SHA256", "MANIFEST_ZLIB_BASE64"}:
                assignments[name] = ast.literal_eval(node.value)
    if set(assignments) != {"FROZEN_CANONICAL_SHA256", "MANIFEST_ZLIB_BASE64"}:
        raise ValueError("notebook does not contain exactly one frozen manifest/hash assignment")
    manifest = json.loads(zlib.decompress(base64.b64decode(assignments["MANIFEST_ZLIB_BASE64"])).decode("utf-8"))
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual = hashlib.sha256(canonical).hexdigest()
    if actual != assignments["FROZEN_CANONICAL_SHA256"]:
        raise ValueError("embedded benchmark manifest hash mismatch")
    return manifest, actual


def expected_tasks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    apis: list[tuple[int, str, str]] = []
    for group in manifest["groups"]:
        for api in group["apis"]:
            apis.append((len(apis), group["id"], api))
    if len(apis) != manifest["target_api_count"]:
        raise ValueError("frozen manifest API count mismatch")
    tasks: dict[str, dict[str, Any]] = {}
    for seed_index, seed in enumerate(manifest["generation_seeds"]):
        for api_index, group, api in apis:
            rotation = (api_index + seed_index) % len(manifest["baseline_ids"])
            logical_order = manifest["baseline_ids"][rotation:] + manifest["baseline_ids"][:rotation]
            task_id = f"{manifest['benchmark_id']}|{api}|{seed}"
            tasks[task_id] = {
                "task_id": task_id, "api": api, "api_group": group, "api_index": api_index,
                "generation_seed": seed, "seed_index": seed_index,
                "logical_baseline_order": logical_order,
                "ab_order": "B2_then_B3" if (seed_index < 4 and seed_index % 2 == 0) or (seed_index == 4 and api_index < 60) else "B3_then_B2",
            }
    return tasks


def validate_event(row: dict[str, Any], line_number: int) -> None:
    missing = REQUIRED_EVENT_FIELDS - set(row)
    if missing:
        raise ValueError(f"line {line_number}: missing event fields {sorted(missing)}")
    if not is_sha256(row["run_signature"]):
        raise ValueError(f"line {line_number}: invalid run signature")
    if row["baseline"] not in BASELINES or row["ab_order"] not in AB_ORDERS:
        raise ValueError(f"line {line_number}: invalid baseline/order")
    for field in ("model", "task_id", "api", "api_group", "seed_backend"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"line {line_number}: {field} must be a non-empty string")
    if not isinstance(row["api_index"], int) or isinstance(row["api_index"], bool) or row["api_index"] < 0:
        raise ValueError(f"line {line_number}: invalid api_index")
    if not isinstance(row["generation_seed"], int) or isinstance(row["generation_seed"], bool):
        raise ValueError(f"line {line_number}: invalid generation_seed")
    if (not isinstance(row["logical_baseline_order"], list)
            or len(row["logical_baseline_order"]) != len(BASELINES)
            or set(row["logical_baseline_order"]) != set(BASELINES)):
        raise ValueError(f"line {line_number}: invalid logical baseline order")
    for field in ("prompt_sha256", "raw_output_sha256"):
        if not is_sha256(row[field]):
            raise ValueError(f"line {line_number}: invalid {field}")
    for field in ("raw_generation", "parseable", "ast_pass", "target_call_present", "oracle_present", "fake_assertion", "runnable", "target_valid", "oracle_bearing"):
        if not isinstance(row[field], bool):
            raise ValueError(f"line {line_number}: {field} is not boolean")
    if row["ast_pass"] and not row["parseable"]:
        raise ValueError(f"line {line_number}: AST-pass event is not parseable")
    if row["runnable"] and not row["ast_pass"]:
        raise ValueError(f"line {line_number}: runnable event did not pass AST validation")
    if row["target_valid"] and (not row["runnable"] or not row["target_call_present"]):
        raise ValueError(f"line {line_number}: target-valid event lacks runnable target call")
    if row["oracle_bearing"] and (
        not row["target_valid"] or not row["oracle_present"] or row["fake_assertion"]
    ):
        raise ValueError(f"line {line_number}: oracle-bearing event violates oracle implications")
    for field in ("generation_seconds", "subprocess_seconds"):
        if not isinstance(row[field], (int, float)) or isinstance(row[field], bool) or row[field] < 0:
            raise ValueError(f"line {line_number}: invalid {field}")
    started, finished = parse_utc(row["started_utc"]), parse_utc(row["finished_utc"])
    if finished < started:
        raise ValueError(f"line {line_number}: finish precedes start")


def load_events(
    path: Path,
    run_signature: str | None = None,
    allow_multiple_signatures: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    rows: list[dict[str, Any]] = []
    truncated_tail = False
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) and not line.endswith(("\n", "\r")):
                truncated_tail = True
                continue
            raise ValueError(f"line {index}: malformed non-tail JSON")
        validate_event(row, index)
        rows.append(row)
    signatures = sorted({row["run_signature"] for row in rows})
    if run_signature is None and len(signatures) > 1 and not allow_multiple_signatures:
        raise ValueError("multiple run signatures; select one with --run-signature")
    selected_signature = run_signature or (signatures[0] if len(signatures) == 1 else None)
    if selected_signature is not None and not is_sha256(selected_signature):
        raise ValueError("requested run signature is invalid")
    selected = rows if selected_signature is None else [row for row in rows if row["run_signature"] == selected_signature]
    if not selected:
        raise ValueError("no events for selected run signature")
    duplicates = [key for key, count in Counter((r["baseline"], r["task_id"]) for r in selected).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate baseline/task events: {duplicates[:5]}")
    return selected, {
        "events_sha256": hashlib.sha256(raw).hexdigest(),
        "all_run_signatures": signatures,
        "selected_run_signature": selected_signature,
        "truncated_tail_ignored": truncated_tail,
        "parsed_event_count_all_signatures": len(rows),
    }


def metric_block(rows: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    total = len(rows)
    generation = sum(float(row["generation_seconds"]) for row in rows)
    subprocess_time = sum(float(row["subprocess_seconds"]) for row in rows)
    event_wall = sum((parse_utc(row["finished_utc"]) - parse_utc(row["started_utc"])).total_seconds() for row in rows)
    result: dict[str, Any] = {
        "expected_events": expected,
        "observed_events": total,
        "complete": total == expected,
        "completion_rate": total / expected if expected else None,
    }
    for field in BOOL_METRICS:
        passed = sum(bool(row[field]) for row in rows)
        result[f"{field}_count"] = passed
        result[f"{field}_rate"] = passed / total if total else None
    result.update({
        "generation_seconds_total": generation if rows else None,
        "subprocess_seconds_total": subprocess_time if rows else None,
        "event_wall_seconds_total": event_wall if rows else None,
        "events_per_hour_event_wall": (total * 3600.0 / event_wall) if event_wall > 0 else None,
    })
    return result


def paired_binary_effects(
    task_ids: list[str], b2: dict[str, dict[str, Any]], b3: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return paired B3-minus-B2 effects without pretending pairs are independent."""
    metrics: dict[str, Any] = {}
    for field in ("parseable", "ast_pass", "runnable", "target_valid", "oracle_bearing"):
        both_pass = b2_only = b3_only = both_fail = 0
        for task_id in task_ids:
            left, right = bool(b2[task_id][field]), bool(b3[task_id][field])
            if left and right:
                both_pass += 1
            elif left:
                b2_only += 1
            elif right:
                b3_only += 1
            else:
                both_fail += 1
        n = len(task_ids)
        discordant = b2_only + b3_only
        if discordant:
            tail = sum(math.comb(discordant, k) for k in range(min(b2_only, b3_only) + 1)) / (2 ** discordant)
            exact_p = min(1.0, 2.0 * tail)
        else:
            exact_p = 1.0 if n else None
        metrics[field] = {
            "eligible_pairs": n,
            "both_pass": both_pass,
            "b2_only_pass": b2_only,
            "b3_only_pass": b3_only,
            "both_fail": both_fail,
            "b2_pass_rate": ((both_pass + b2_only) / n) if n else None,
            "b3_pass_rate": ((both_pass + b3_only) / n) if n else None,
            "b3_minus_b2_paired_rate": ((b3_only - b2_only) / n) if n else None,
            "discordant_pairs": discordant,
            "mcnemar_exact_two_sided_p": exact_p,
        }
    return metrics


def summarize(
    events_path: Path,
    notebook: Path,
    evidence_label: str,
    run_signature: str | None = None,
    allow_multiple_signatures: bool = False,
    configuration_equivalence_verified: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if evidence_label not in {"validation_only", "campaign"}:
        raise ValueError("invalid evidence label")
    manifest, manifest_hash = load_frozen_manifest(notebook)
    tasks = expected_tasks(manifest)
    rows, stream = load_events(events_path, run_signature, allow_multiple_signatures)
    expected_baselines = tuple(manifest["baseline_ids"])
    expected_seeds = tuple(manifest["generation_seeds"])
    groups = [group["id"] for group in manifest["groups"]]

    mismatches: list[dict[str, Any]] = []
    extra_task_ids: list[str] = []
    for row in rows:
        expected = tasks.get(row["task_id"])
        if expected is None:
            extra_task_ids.append(row["task_id"])
            continue
        for field in ("api", "api_group", "api_index", "generation_seed", "ab_order", "logical_baseline_order"):
            if row[field] != expected[field]:
                mismatches.append({"baseline": row["baseline"], "task_id": row["task_id"], "field": field})

    observed_keys = {(row["baseline"], row["task_id"]) for row in rows}
    missing_keys = [(baseline, task_id) for task_id in tasks for baseline in expected_baselines if (baseline, task_id) not in observed_keys]
    unexpected_baselines = sorted({row["baseline"] for row in rows} - set(expected_baselines))

    by_baseline = {baseline: metric_block([r for r in rows if r["baseline"] == baseline], len(tasks)) for baseline in expected_baselines}
    by_seed = {
        str(seed): metric_block([r for r in rows if r["generation_seed"] == seed], manifest["target_api_count"] * len(expected_baselines))
        for seed in expected_seeds
    }
    cells: list[dict[str, Any]] = []
    for baseline in expected_baselines:
        for group in groups:
            for seed in expected_seeds:
                selected = [r for r in rows if r["baseline"] == baseline and r["api_group"] == group and r["generation_seed"] == seed]
                cells.append({"baseline": baseline, "api_group": group, "generation_seed": seed, **metric_block(selected, manifest["apis_per_group"])})

    b2 = {row["task_id"]: row for row in rows if row["baseline"] == "B2"}
    b3 = {row["task_id"]: row for row in rows if row["baseline"] == "B3"}
    common = sorted(set(b2) & set(b3))
    prompt_mismatch = [task for task in common if b2[task]["prompt_sha256"] != b3[task]["prompt_sha256"]]
    seed_backend_fail = [
        row["task_id"] for row in rows if row["baseline"] in {"B1", "B2", "B3"}
        and "completion(seed)" not in row["seed_backend"]
    ]
    raw_generation_fail = [row["task_id"] for row in rows if not row["raw_generation"]]
    model_labels = {
        baseline: sorted({row["model"] for row in rows if row["baseline"] == baseline})
        for baseline in expected_baselines
    }
    model_label_inconsistent = [baseline for baseline, labels in model_labels.items() if len(labels) > 1]
    expected_order_counts = Counter(task["ab_order"] for task in tasks.values())
    observed_pair_order_counts = Counter(b2[task]["ab_order"] for task in common if b2[task]["ab_order"] == b3[task]["ab_order"])
    pair_order_mismatch = [task for task in common if b2[task]["ab_order"] != b3[task]["ab_order"]]
    eligible_paired_tasks = sorted(set(common) - set(prompt_mismatch) - set(pair_order_mismatch))
    paired_effects = paired_binary_effects(eligible_paired_tasks, b2, b3)
    paired_by_group = {
        group: {
            "eligible_pair_count": len(selected),
            "metrics": paired_binary_effects(selected, b2, b3),
        }
        for group in groups
        for selected in [[task_id for task_id in eligible_paired_tasks if tasks[task_id]["api_group"] == group]]
    }
    paired_by_seed = {
        str(seed): {
            "eligible_pair_count": len(selected),
            "metrics": paired_binary_effects(selected, b2, b3),
        }
        for seed in expected_seeds
        for selected in [[task_id for task_id in eligible_paired_tasks if tasks[task_id]["generation_seed"] == seed]]
    }
    pair_complete = len(common) == len(tasks)
    logical_position_counts = Counter(
        (baseline, task["logical_baseline_order"].index(baseline))
        for task in tasks.values() for baseline in expected_baselines
    )
    expected_position_count = len(tasks) // len(expected_baselines)
    logical_schedule_balanced = (
        len(logical_position_counts) == len(expected_baselines) ** 2
        and set(logical_position_counts.values()) == {expected_position_count}
    )
    observed_signature_counts = Counter(row["run_signature"] for row in rows)
    signatures_by_seed = {
        str(seed): sorted({row["run_signature"] for row in rows if row["generation_seed"] == seed})
        for seed in expected_seeds
    }
    single_run_signature = len({row["run_signature"] for row in rows}) == 1
    harness_equivalence_verified = single_run_signature or configuration_equivalence_verified
    fairness = {
        "same_harness_run_signature": single_run_signature,
        "configuration_equivalence_verified": configuration_equivalence_verified,
        "harness_equivalence_verified": harness_equivalence_verified,
        "observed_run_signature_counts": dict(observed_signature_counts),
        "run_signatures_by_seed": signatures_by_seed,
        "logical_schedule_balanced": logical_schedule_balanced,
        "expected_logical_position_count": expected_position_count,
        "logical_position_counts": {
            f"{baseline}@{position}": logical_position_counts[(baseline, position)]
            for baseline in expected_baselines for position in range(len(expected_baselines))
        },
        "b2_events": len(b2), "b3_events": len(b3), "complete_b2_b3_pairs": len(common),
        "expected_b2_b3_pairs": len(tasks), "pair_complete": pair_complete,
        "prompt_hash_mismatch_count": len(prompt_mismatch),
        "prompt_hash_mismatch_task_ids": prompt_mismatch,
        "pair_order_mismatch_count": len(pair_order_mismatch),
        "pair_order_mismatch_task_ids": pair_order_mismatch,
        "paired_outcomes": {
            "eligibility": "complete B2/B3 pair with identical prompt hash and A/B order metadata",
            "eligible_pair_count": len(eligible_paired_tasks),
            "metrics": paired_effects,
            "by_api_group": paired_by_group,
            "by_generation_seed": paired_by_seed,
        },
        "expected_pair_order_counts": dict(expected_order_counts),
        "observed_complete_pair_order_counts": dict(observed_pair_order_counts),
        "full_order_balance_verified": pair_complete and observed_pair_order_counts == expected_order_counts,
        "seed_backend_failure_count": len(seed_backend_fail),
        "seed_backend_failure_task_ids": seed_backend_fail,
        "raw_generation_failure_count": len(raw_generation_fail),
        "raw_generation_failure_task_ids": raw_generation_fail,
        "model_labels_by_baseline": model_labels,
        "model_label_inconsistent_baselines": model_label_inconsistent,
    }

    starts = [parse_utc(row["started_utc"]) for row in rows]
    finishes = [parse_utc(row["finished_utc"]) for row in rows]
    span = (max(finishes) - min(starts)).total_seconds() if rows else None
    total_event_wall = sum((parse_utc(row["finished_utc"]) - parse_utc(row["started_utc"])).total_seconds() for row in rows)
    complete = (
        len(rows) == len(tasks) * len(expected_baselines) and not missing_keys and not extra_task_ids
        and not mismatches and not unexpected_baselines and not stream["truncated_tail_ignored"]
        and fairness["harness_equivalence_verified"] and fairness["pair_complete"]
        and not prompt_mismatch and not pair_order_mismatch and fairness["full_order_balance_verified"]
        and not seed_backend_fail and not raw_generation_fail and not model_label_inconsistent
    )
    blockers: list[str] = []
    if evidence_label != "campaign": blockers.append("evidence_label_is_not_campaign")
    if stream["truncated_tail_ignored"]: blockers.append("truncated_tail_ignored")
    if missing_keys: blockers.append("expected_events_missing")
    if extra_task_ids: blockers.append("unexpected_task_ids")
    if mismatches: blockers.append("frozen_task_metadata_mismatch")
    if unexpected_baselines: blockers.append("unexpected_baselines")
    if not fairness["harness_equivalence_verified"]: blockers.append("multiple_run_signatures_without_verified_equivalence")
    if not fairness["pair_complete"]: blockers.append("b2_b3_pairs_incomplete")
    if prompt_mismatch: blockers.append("b2_b3_prompt_mismatch")
    if pair_order_mismatch: blockers.append("b2_b3_order_mismatch")
    if fairness["pair_complete"] and not fairness["full_order_balance_verified"]: blockers.append("b2_b3_order_not_balanced")
    if seed_backend_fail: blockers.append("llm_decoding_seed_not_logged")
    if raw_generation_fail: blockers.append("raw_generation_not_preserved")
    if model_label_inconsistent: blockers.append("baseline_model_label_inconsistent")
    return {
        "schema_version": "trdgl_benchmark_result_summary_v1",
        "evidence_label": evidence_label,
        "benchmark": {
            "benchmark_id": manifest["benchmark_id"], "manifest_sha256": manifest_hash,
            "api_count": manifest["target_api_count"], "api_group_count": manifest["group_count"],
            "apis_per_group": manifest["apis_per_group"], "generation_seeds": list(expected_seeds),
            "baselines": list(expected_baselines), "expected_task_count": len(tasks),
            "expected_event_count": len(tasks) * len(expected_baselines),
        },
        "source": {"events_path": events_path.as_posix(), "notebook_path": notebook.as_posix(), **stream},
        "coverage": {
            "observed_event_count": len(rows), "missing_event_count": len(missing_keys),
            "unexpected_task_count": len(set(extra_task_ids)), "metadata_mismatch_count": len(mismatches),
            "missing_events_sample": [{"baseline": b, "task_id": t} for b, t in missing_keys[:20]],
            "unexpected_task_ids": sorted(set(extra_task_ids))[:20], "metadata_mismatches_sample": mismatches[:20],
            "by_baseline": by_baseline,
            "by_seed": by_seed,
        },
        "fairness": fairness,
        "runtime": {
            "event_wall_seconds_total": total_event_wall,
            "campaign_span_seconds": span,
            "events_per_hour_event_wall": len(rows) * 3600.0 / total_event_wall if total_event_wall > 0 else None,
            "events_per_hour_campaign_span": len(rows) * 3600.0 / span if span and span > 0 else None,
            "campaign_span_includes_idle_or_restart_gaps": True,
        },
        "full_benchmark_complete": complete,
        "ready_for_paper_result": evidence_label == "campaign" and complete,
        "blockers": blockers,
    }, cells


def write_cells(path: Path, cells: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cells[0]))
        writer.writeheader()
        writer.writerows(cells)


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    """Write a compact, source-hashed checkpoint without promoting partial data."""
    coverage = summary["coverage"]
    fairness = summary["fairness"]
    runtime = summary["runtime"]
    lines = [
        "# Frozen benchmark checkpoint",
        "",
        f"- Evidence label: `{summary['evidence_label']}`",
        f"- Event stream SHA-256: `{summary['source']['events_sha256']}`",
        f"- Observed / expected events: **{coverage['observed_event_count']} / {summary['benchmark']['expected_event_count']}**",
        f"- Full benchmark complete: **{str(summary['full_benchmark_complete']).lower()}**",
        f"- Ready for paper result: **{str(summary['ready_for_paper_result']).lower()}**",
        f"- Blockers: {', '.join(f'`{item}`' for item in summary['blockers']) or 'none'}",
        "",
        "## Baseline coverage and outcomes",
        "",
        "| Baseline | Observed | Parseable | AST pass | Runnable | Target valid | Oracle bearing |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for baseline, metrics in coverage["by_baseline"].items():
        lines.append(
            f"| {baseline} | {metrics['observed_events']} / {metrics['expected_events']} "
            f"| {metrics['parseable_count']} | {metrics['ast_pass_count']} | {metrics['runnable_count']} "
            f"| {metrics['target_valid_count']} | {metrics['oracle_bearing_count']} |"
        )
    lines.extend([
        "",
        "## Seed completion",
        "",
        "| Seed | Observed | Expected | Complete |",
        "|---:|---:|---:|:---:|",
    ])
    for seed, metrics in coverage["by_seed"].items():
        lines.append(f"| {seed} | {metrics['observed_events']} | {metrics['expected_events']} | {str(metrics['complete']).lower()} |")
    lines.extend([
        "",
        "## Fairness and throughput",
        "",
        f"- Complete B2/B3 pairs: {fairness['complete_b2_b3_pairs']} / {fairness['expected_b2_b3_pairs']}",
        f"- B2/B3 prompt-hash mismatches among complete pairs: {fairness['prompt_hash_mismatch_count']}",
        f"- Contract-eligible paired comparisons: {fairness['paired_outcomes']['eligible_pair_count']}",
        f"- Frozen logical Latin schedule balanced: {str(fairness['logical_schedule_balanced']).lower()}",
        f"- Full physical A/B order balance verified: {str(fairness['full_order_balance_verified']).lower()}",
        f"- Event-wall throughput: {runtime['events_per_hour_event_wall']}",
        f"- Campaign-span throughput (includes idle/restart gaps): {runtime['events_per_hour_campaign_span']}",
        "",
        "Partial rows and rates are checkpoint evidence only. They must not be described as a completed campaign.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_coverage_rows(
    notebook: Path,
    events_path: Path,
    run_signature: str | None = None,
    allow_multiple_signatures: bool = False,
) -> list[dict[str, Any]]:
    manifest, _ = load_frozen_manifest(notebook)
    tasks = expected_tasks(manifest)
    events, _ = load_events(events_path, run_signature, allow_multiple_signatures)
    indexed = {(row["baseline"], row["task_id"]): row for row in events}
    coverage: list[dict[str, Any]] = []
    for task in tasks.values():
        for baseline in manifest["baseline_ids"]:
            row = indexed.get((baseline, task["task_id"]))
            coverage.append({
                "baseline": baseline,
                "task_id": task["task_id"],
                "api": task["api"],
                "api_group": task["api_group"],
                "generation_seed": task["generation_seed"],
                "ab_order": task["ab_order"],
                "observed": row is not None,
                "parseable": row["parseable"] if row else None,
                "ast_pass": row["ast_pass"] if row else None,
                "runnable": row["runnable"] if row else None,
                "target_valid": row["target_valid"] if row else None,
                "oracle_bearing": row["oracle_bearing"] if row else None,
                "generation_seconds": row["generation_seconds"] if row else None,
                "subprocess_seconds": row["subprocess_seconds"] if row else None,
                "raw_output_sha256": row["raw_output_sha256"] if row else None,
            })
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--cells-csv", type=Path, required=True)
    parser.add_argument("--coverage-csv", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--evidence-label", choices=("validation_only", "campaign"), default="validation_only")
    parser.add_argument("--run-signature")
    args = parser.parse_args()
    summary, cells = summarize(args.events, args.notebook, args.evidence_label, args.run_signature)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_cells(args.cells_csv, cells)
    write_cells(args.coverage_csv, build_coverage_rows(args.notebook, args.events, args.run_signature))
    if args.report_md:
        write_markdown(args.report_md, summary)
    print(json.dumps({"observed": summary["coverage"]["observed_event_count"], "expected": summary["benchmark"]["expected_event_count"], "complete": summary["full_benchmark_complete"], "ready": summary["ready_for_paper_result"], "blockers": summary["blockers"]}, indent=2))


if __name__ == "__main__":
    main()
