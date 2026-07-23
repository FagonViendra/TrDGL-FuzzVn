#!/usr/bin/env python3
"""Build a deterministic manual-review sample and compute reviewer agreement."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analyze_generation_errors import (
    CATEGORIES, LOADED_ANALYZER_SHA256, VERSION, classify_record, harness_expected_labels,
    load_source, rate, write_csv,
)


LABELS = ("true", "false", "unknown")
REVIEW_TOOL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def stable_key(record: dict[str, Any]) -> str:
    material = "|".join(
        str(record.get(name) or "")
        for name in ("run_signature", "task_id", "baseline", "api", "generation_seed", "_source_record_index")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_sample(input_path: Path, output_dir: Path, sample_size: int = 24) -> dict[str, Any]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    records, source = load_source(input_path)
    buckets: dict[str, list[tuple[str, dict[str, Any], dict[str, bool | None], dict[str, str]]]] = defaultdict(list)
    population_auto_label_counts: dict[str, Counter[str]] = {
        category: Counter() for category in CATEGORIES
    }
    for record in records:
        status, evidence = classify_record(record)
        for category in CATEGORIES:
            label = "unknown" if status[category] is None else str(status[category]).lower()
            population_auto_label_counts[category][label] += 1
        positives = [category for category in CATEGORIES if status[category] is True]
        harness_labels = harness_expected_labels(record)
        disagreements = [
            f"harness_disagreement_{category}"
            for category, expected in harness_labels.items()
            if expected is not None and status.get(category) is not None and expected is not status[category]
        ]
        # A generation can exhibit several failure modes. Put it in every
        # positive-label stratum, then de-duplicate during selection. Using
        # only the first positive category would hide rarer secondary labels.
        labels = positives + disagreements or ["no_detected_failure"]
        for label in labels:
            stratum = f"{record.get('baseline', '__UNKNOWN__')}:{label}"
            buckets[stratum].append((stable_key(record), record, status, evidence))
    population_stratum_candidate_counts = {
        stratum: len(bucket) for stratum, bucket in sorted(buckets.items())
    }
    for bucket in buckets.values():
        bucket.sort(key=lambda item: item[0])

    selected: list[tuple[str, str, dict[str, Any], dict[str, bool | None], dict[str, str]]] = []
    selected_keys: set[str] = set()
    ordered_strata = sorted(buckets)
    cursor = 0
    while len(selected) < min(sample_size, len(records)) and ordered_strata:
        stratum = ordered_strata[cursor % len(ordered_strata)]
        bucket = buckets[stratum]
        if bucket:
            key, record, status, evidence = bucket.pop(0)
            if key not in selected_keys:
                selected_keys.add(key)
                selected.append((key, stratum, record, status, evidence))
        if not bucket:
            ordered_strata.remove(stratum)
            if not ordered_strata:
                break
            cursor %= len(ordered_strata)
        else:
            cursor += 1

    rows: list[dict[str, Any]] = []
    for key, stratum, record, status, evidence in selected:
        row: dict[str, Any] = {
            "review_key": f"{source['sha256']}:{record['_source_record_index']}",
            "source_sha256": source["sha256"],
            "analyzer_sha256": LOADED_ANALYZER_SHA256,
            "review_tool_sha256": REVIEW_TOOL_SHA256,
            "source_record_index": record["_source_record_index"],
            "selection_hash": key,
            "selection_stratum": stratum,
            "baseline": record.get("baseline"),
            "api_group": record.get("api_group"),
            "api": record.get("api"),
            "generation_seed": record.get("generation_seed"),
            "finish_reason": record.get("finish_reason"),
            "exit_code": record.get("exit_code"),
            "timeout": record.get("timeout"),
            "extracted_code": record.get("extracted_code") or record.get("raw_output") or "",
            "stderr": record.get("stderr") or "",
            "auto_evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            "reviewer_id": "",
            "review_notes": "",
        }
        for category in CATEGORIES:
            row[f"auto_{category}"] = (
                "unknown" if status[category] is None else str(status[category]).lower()
            )
            row[f"review_{category}"] = ""
        rows.append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "review_key", "source_sha256", "analyzer_sha256", "review_tool_sha256",
        "source_record_index", "selection_hash", "selection_stratum",
        "baseline", "api_group", "api", "generation_seed", "finish_reason", "exit_code", "timeout",
        "extracted_code", "stderr", "auto_evidence_json", "reviewer_id", "review_notes",
    ] + [item for category in CATEGORIES for item in (f"auto_{category}", f"review_{category}")]
    write_csv(output_dir / "review_sample.csv", rows, fields)
    manifest = {
        "schema_version": VERSION,
        "analyzer_sha256": LOADED_ANALYZER_SHA256,
        "review_tool_sha256": REVIEW_TOOL_SHA256,
        "status": "awaiting_two_independent_reviewers",
        "source": source,
        "population_records": len(records),
        "requested_sample_size": sample_size,
        "selected_records": len(rows),
        "selection": (
            "deterministic round-robin over all baseline:positive-auto-label and harness-disagreement strata "
            "with record de-duplication; "
            "no-detected-failure is a fallback stratum; SHA-256 order within stratum"
        ),
        "population_stratum_candidate_counts": population_stratum_candidate_counts,
        "stratum_counts": dict(sorted(Counter(row["selection_stratum"] for row in rows).items())),
        "population_auto_label_counts": {
            category: dict(sorted(counts.items()))
            for category, counts in population_auto_label_counts.items()
        },
        "sample_auto_label_counts": {
            category: dict(sorted(Counter(row[f"auto_{category}"] for row in rows).items()))
            for category in CATEGORIES
        },
        "allowed_review_labels": list(LABELS),
        "instructions": (
            "Make two copies of review_sample.csv. Each reviewer independently fills reviewer_id, "
            "review_<category> with true/false/unknown, and optional review_notes. Do not edit auto_* columns."
        ),
    }
    (output_dir / "review_sample_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def normalize_label(value: str, location: str) -> str | None:
    token = value.strip().lower()
    if not token:
        return None
    if token not in LABELS:
        raise ValueError(f"{location}: expected true/false/unknown or blank, got {value!r}")
    return token


def cohen_kappa(pairs: list[tuple[str, str]]) -> tuple[float | None, float | None]:
    if not pairs:
        return None, None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    expected = sum((left[label] / n) * (right[label] / n) for label in LABELS)
    if expected == 1.0:
        # With no marginal variation, kappa has a zero denominator.  Raw
        # agreement remains reportable but kappa is mathematically undefined.
        return observed, None
    return observed, (observed - expected) / (1.0 - expected)


def read_reviews(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, 2):
        key = row.get("review_key", "")
        if not key:
            raise ValueError(f"{path}:{index}: missing review_key")
        if key in result:
            raise ValueError(f"{path}:{index}: duplicate review_key {key}")
        result[key] = row
    return result


def compute_agreement(reviewer_a: Path, reviewer_b: Path, output_dir: Path) -> dict[str, Any]:
    left = read_reviews(reviewer_a)
    right = read_reviews(reviewer_b)
    shared = sorted(set(left) & set(right))
    sample_pins: dict[str, str] = {}
    for field in ("analyzer_sha256", "review_tool_sha256"):
        left_values = {row.get(field, "").strip() for row in left.values()} - {""}
        right_values = {row.get(field, "").strip() for row in right.values()} - {""}
        if len(left_values) != 1 or len(right_values) != 1 or left_values != right_values:
            raise ValueError(f"review sample has missing or inconsistent {field}")
        sample_pins[field] = next(iter(left_values))
    immutable_fields = (
        "source_sha256", "analyzer_sha256", "review_tool_sha256",
        "source_record_index", "selection_hash", "selection_stratum",
        "baseline", "api_group", "api", "generation_seed",
        "finish_reason", "exit_code", "timeout", "extracted_code", "stderr", "auto_evidence_json",
        *(f"auto_{category}" for category in CATEGORIES),
    )
    for key in shared:
        changed = [field for field in immutable_fields if left[key].get(field, "") != right[key].get(field, "")]
        if changed:
            raise ValueError(f"review metadata differs for {key}: {', '.join(changed)}")
    rows: list[dict[str, Any]] = []
    for category in CATEGORIES:
        pairs: list[tuple[str, str]] = []
        confusion: Counter[str] = Counter()
        auto_consensus_pairs: list[tuple[str, str]] = []
        auto_consensus_confusion: Counter[str] = Counter()
        for key in shared:
            a = normalize_label(left[key].get(f"review_{category}", ""), f"{reviewer_a}:{key}:{category}")
            b = normalize_label(right[key].get(f"review_{category}", ""), f"{reviewer_b}:{key}:{category}")
            if a is None or b is None:
                continue
            pairs.append((a, b))
            confusion[f"{a}->{b}"] += 1
            if a == b:
                auto = normalize_label(
                    left[key].get(f"auto_{category}", ""),
                    f"{reviewer_a}:{key}:auto_{category}",
                )
                if auto is not None:
                    auto_consensus_pairs.append((auto, a))
                    auto_consensus_confusion[f"{auto}->{a}"] += 1
        agreement, kappa = cohen_kappa(pairs)
        auto_consensus_agreement = rate(
            sum(auto == consensus for auto, consensus in auto_consensus_pairs),
            len(auto_consensus_pairs),
        )
        rows.append({
            "category": category,
            "shared_records": len(shared),
            "paired_labels": len(pairs),
            "raw_agreement": agreement,
            "cohen_kappa": kappa,
            "confusion_json": json.dumps(dict(sorted(confusion.items())), sort_keys=True),
            "reviewer_consensus_labels": len(auto_consensus_pairs),
            "auto_vs_consensus_agreement": auto_consensus_agreement,
            "auto_vs_consensus_confusion_json": json.dumps(
                dict(sorted(auto_consensus_confusion.items())), sort_keys=True
            ),
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "reviewer_agreement.csv", rows)
    reviewer_ids_a = sorted({row.get("reviewer_id", "").strip() for row in left.values()} - {""})
    reviewer_ids_b = sorted({row.get("reviewer_id", "").strip() for row in right.values()} - {""})
    identities_distinct = (
        len(reviewer_ids_a) == len(reviewer_ids_b) == 1
        and reviewer_ids_a[0] != reviewer_ids_b[0]
        and all(row.get("reviewer_id", "").strip() == reviewer_ids_a[0] for row in left.values())
        and all(row.get("reviewer_id", "").strip() == reviewer_ids_b[0] for row in right.values())
    )
    expected_pairs = len(shared) * len(CATEGORIES)
    paired_labels = sum(row["paired_labels"] for row in rows)
    same_record_set = set(left) == set(right)
    labels_complete = bool(shared) and same_record_set and paired_labels == expected_pairs
    if labels_complete and identities_distinct:
        status = "complete"
    elif labels_complete:
        status = "labels_complete_identity_unverified"
    elif paired_labels:
        status = "pending_partial_reviews"
    else:
        status = "pending_unfilled_reviews"
    result = {
        "schema_version": VERSION,
        "analyzer_sha256": LOADED_ANALYZER_SHA256,
        "review_tool_sha256": REVIEW_TOOL_SHA256,
        "sample_analyzer_sha256": sample_pins["analyzer_sha256"],
        "sample_review_tool_sha256": sample_pins["review_tool_sha256"],
        "sample_tools_match_current": (
            sample_pins["analyzer_sha256"] == LOADED_ANALYZER_SHA256
            and sample_pins["review_tool_sha256"] == REVIEW_TOOL_SHA256
        ),
        "status": status,
        "reviewer_a": str(reviewer_a.resolve()),
        "reviewer_b": str(reviewer_b.resolve()),
        "reviewer_ids_a": reviewer_ids_a,
        "reviewer_ids_b": reviewer_ids_b,
        "identities_distinct": identities_distinct,
        "same_record_set": same_record_set,
        "shared_records": len(shared),
        "expected_label_pairs": expected_pairs,
        "paired_labels": paired_labels,
        "categories": rows,
    }
    (output_dir / "reviewer_agreement.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--input", required=True, type=Path)
    sample.add_argument("--output-dir", required=True, type=Path)
    sample.add_argument("--sample-size", type=int, default=24)
    agreement = sub.add_parser("agreement")
    agreement.add_argument("--reviewer-a", required=True, type=Path)
    agreement.add_argument("--reviewer-b", required=True, type=Path)
    agreement.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "sample":
        result = build_sample(args.input, args.output_dir, args.sample_size)
    else:
        result = compute_agreement(args.reviewer_a, args.reviewer_b, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
