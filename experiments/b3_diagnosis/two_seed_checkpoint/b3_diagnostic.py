#!/usr/bin/env python3
"""Deterministic, CPU-only diagnostics for the frozen B2/B3 JSONL evidence.

The analyzer never writes to or rewrites evidence files. It reads the package,
validates packaged SHA-256 values, recomputes event/pair metrics, and writes only
new diagnostic artifacts.
"""
from __future__ import annotations

import argparse
import ast
import codeop
import csv
import hashlib
import io
import json
import math
import re
import statistics
import tokenize
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = "trdgl_b3_independent_diagnostic_v1"
TURN_EXACT_RE = re.compile(r"<(?:start|end)_of_turn>")
TURN_PREFIX_RE = re.compile(r"<(?:start|end)_of")
ROLE_RE = re.compile(r"<start_of_turn>(system|user|model|assistant)")
WORD_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|<[^>\n]+>|\d+(?:\.\d+)?|[^\s]")
PROMPT_ECHO_PHRASES = (
    "Generate a unit test",
    "Generate rigorous PyTorch API tests",
    "Create a tiny deterministic CPU test",
    "Requirements:",
    "Target API:",
    "Output exactly one",
    "Documentation snapshot:",
    "Start with import torch",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            row["_jsonl_line"] = line_no
            rows.append(row)
    return rows


def lexical_tokens(text: str) -> list[str]:
    return WORD_TOKEN_RE.findall(text)


def nearest_rank(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return float(ordered[rank - 1])


def numeric_summary(values: Iterable[float]) -> dict[str, Any]:
    vals = [float(v) for v in values]
    if not vals:
        return {"n": 0, "min": None, "median": None, "mean": None, "p95": None, "max": None}
    return {
        "n": len(vals),
        "min": min(vals),
        "median": statistics.median(vals),
        "mean": statistics.fmean(vals),
        "p95": nearest_rank(vals, 0.95),
        "max": max(vals),
    }


def bracket_and_tokenize_features(text: str) -> tuple[str, str]:
    stack: list[str] = []
    token_error = ""
    pairs = {")": "(", "]": "[", "}": "{"}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.OP:
                continue
            if tok.string in "([{":
                stack.append(tok.string)
            elif tok.string in ")]}" and stack and stack[-1] == pairs[tok.string]:
                stack.pop()
    except (tokenize.TokenError, IndentationError) as exc:
        token_error = str(exc)
    return "".join(stack), token_error


def compile_status(code: str) -> str:
    try:
        result = codeop.compile_command(code, symbol="exec")
        return "complete" if result is not None else "incomplete"
    except (SyntaxError, OverflowError, ValueError):
        return "invalid"


def ngram_stats(text: str, n: int) -> dict[str, Any]:
    tokens = [token.lower() for token in lexical_tokens(text)]
    grams = [tuple(tokens[i : i + n]) for i in range(max(0, len(tokens) - n + 1))]
    counts = Counter(grams)
    total = len(grams)
    unique = len(counts)
    return {
        "n": n,
        "total": total,
        "unique": unique,
        "repeat_fraction": (1.0 - unique / total) if total else 0.0,
        "max_count": max(counts.values(), default=0),
    }


def repeated_suffix_tokens(text: str, min_block: int = 4, max_block: int = 80) -> tuple[int, int]:
    tokens = lexical_tokens(text)
    max_block = min(max_block, len(tokens) // 2)
    best_block = 0
    best_repetitions = 1
    best_coverage = 0
    for block_size in range(min_block, max_block + 1):
        block = tokens[-block_size:]
        repetitions = 1
        while (repetitions + 1) * block_size <= len(tokens):
            left = -(repetitions + 1) * block_size
            right = -repetitions * block_size
            if tokens[left:right] != block:
                break
            repetitions += 1
        coverage = block_size * repetitions
        if repetitions >= 2 and coverage > best_coverage:
            best_block = block_size
            best_repetitions = repetitions
            best_coverage = coverage
    return best_block, best_repetitions


def role_sequence(text: str) -> str:
    roles = ROLE_RE.findall(text)
    return ">".join(roles) if roles else "(none)"


def ending_features(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_output", "") or ""
    code = row.get("extracted_code", "") or ""
    ast_reason = (row.get("ast_reason", "") or "").lower()
    unclosed_brackets, token_error = bracket_and_tokenize_features(code)
    significant_lines = [line.rstrip() for line in code.splitlines() if line.strip()]
    last_line = significant_lines[-1] if significant_lines else ""
    unclosed_block = bool(
        re.match(
            r"^\s*(?:async\s+)?(?:def|class|if|elif|else|for|while|try|except|finally|with|match|case)\b.*:\s*(?:#.*)?$",
            last_line,
        )
    )
    unclosed_quote = any(
        marker in ast_reason
        for marker in ("unterminated string", "unterminated triple-quoted", "f-string: expecting")
    )
    block_size, repetitions = repeated_suffix_tokens(raw)
    return {
        "exact_turn_delimiter": bool(TURN_EXACT_RE.search(raw)),
        "turn_delimiter_or_prefix": bool(TURN_PREFIX_RE.search(raw)),
        "end_of_turn_count": raw.count("<end_of_turn>"),
        "start_of_turn_count": raw.count("<start_of_turn>"),
        "role_sequence": role_sequence(raw),
        "markdown_fence_count": raw.count("```") + raw.count("~~~"),
        "unclosed_markdown_fence": bool(raw.count("```") % 2 or raw.count("~~~") % 2),
        "unclosed_quote": unclosed_quote,
        "unclosed_brackets": unclosed_brackets,
        "unclosed_bracket_depth": len(unclosed_brackets),
        "unclosed_block_at_eof": unclosed_block,
        "compile_status": compile_status(code),
        "tokenize_error": token_error,
        "repeated_suffix_block_tokens": block_size,
        "repeated_suffix_repetitions": repetitions,
        "ngram4": ngram_stats(raw, 4),
        "ngram8": ngram_stats(raw, 8),
        "output_chars": len(raw),
        "output_bytes": len(raw.encode("utf-8")),
        "output_lines": raw.count("\n") + 1,
        "last_non_whitespace_char": raw.rstrip()[-1:] if raw.rstrip() else "",
        "prompt_echo_phrases": [phrase for phrase in PROMPT_ECHO_PHRASES if phrase.lower() in raw.lower()],
    }


def failure_cluster(row: dict[str, Any], features: dict[str, Any]) -> str:
    if features["turn_delimiter_or_prefix"]:
        return "turn_delimiter_runaway_parseable" if row.get("parseable") else "turn_delimiter_runaway_syntax"
    reason = (row.get("ast_reason", "") or "").lower()
    truncated = (
        features["compile_status"] == "incomplete"
        or features["unclosed_bracket_depth"] > 0
        or features["unclosed_quote"]
        or "was never closed" in reason
        or (row.get("raw_output", "") or "").rstrip().endswith(("<end_of", "<start_of"))
    )
    if not row.get("parseable") and truncated:
        return "marker_free_truncated_code"
    if row.get("parseable"):
        if row.get("target_valid"):
            return "marker_free_target_valid_no_oracle" if not row.get("oracle_bearing") else "marker_free_oracle_bearing"
        if row.get("runnable"):
            return "marker_free_runnable_wrong_api"
        return "marker_free_parseable_runtime"
    return "marker_free_invalid_or_prompt_echo"


def exact_mcnemar_two_sided(b2_only: int, b3_only: int) -> float:
    discordant = b2_only + b3_only
    if discordant == 0:
        return 1.0
    lower = min(b2_only, b3_only)
    probability = 2.0 * sum(math.comb(discordant, i) for i in range(lower + 1)) / (2**discordant)
    return min(1.0, probability)


def metric_pair_summary(pairs: list[dict[str, dict[str, Any]]], metric: str) -> dict[str, Any]:
    both = b2_only = b3_only = neither = 0
    for pair in pairs:
        a = bool(pair["B2"][metric])
        b = bool(pair["B3"][metric])
        if a and b:
            both += 1
        elif a:
            b2_only += 1
        elif b:
            b3_only += 1
        else:
            neither += 1
    return {
        "eligible_pairs": len(pairs),
        "both_pass": both,
        "b2_only_pass": b2_only,
        "b3_only_pass": b3_only,
        "both_fail": neither,
        "b2_pass_rate": (both + b2_only) / len(pairs) if pairs else None,
        "b3_pass_rate": (both + b3_only) / len(pairs) if pairs else None,
        "b3_minus_b2_paired_rate": (b3_only - b2_only) / len(pairs) if pairs else None,
        "discordant_pairs": b2_only + b3_only,
        "mcnemar_exact_two_sided_p": exact_mcnemar_two_sided(b2_only, b3_only),
    }


def shingle_set(text: str, n: int = 5) -> set[tuple[str, ...]]:
    tokens = [token.lower() for token in lexical_tokens(text)]
    return {tuple(tokens[i : i + n]) for i in range(max(0, len(tokens) - n + 1))}


def jaccard(left: set[Any], right: set[Any]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def cross_api_similarity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    shingles = [shingle_set(row.get("raw_output", ""), 5) for row in rows]
    values: list[float] = []
    for i, left in enumerate(rows):
        for j in range(i + 1, len(rows)):
            if left["api"] == rows[j]["api"]:
                continue
            values.append(jaccard(shingles[i], shingles[j]))
    return {
        "pair_count": len(values),
        "median": statistics.median(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "p90_nearest_rank": nearest_rank(values, 0.90),
        "p99_nearest_rank": nearest_rank(values, 0.99),
        "max": max(values) if values else None,
    }


def summarize_baseline(rows: list[dict[str, Any]], features_by_line: dict[int, dict[str, Any]]) -> dict[str, Any]:
    finish = Counter(row.get("finish_reason") for row in rows)
    error_keys = Counter(",".join(row.get("error_labels") or []) or "none" for row in rows)
    return {
        "events": len(rows),
        "finish_reasons": dict(sorted(finish.items(), key=lambda item: str(item[0]))),
        "raw_token_count": numeric_summary(row["raw_token_count"] for row in rows if row.get("raw_token_count") is not None),
        "generation_seconds": numeric_summary(row["generation_seconds"] for row in rows),
        "parseable": sum(bool(row.get("parseable")) for row in rows),
        "runnable": sum(bool(row.get("runnable")) for row in rows),
        "target_valid": sum(bool(row.get("target_valid")) for row in rows),
        "oracle_bearing": sum(bool(row.get("oracle_bearing")) for row in rows),
        "unique_raw_output_sha256": len({row.get("raw_output_sha256") for row in rows}),
        "error_classes": dict(sorted(error_keys.items())),
        "exact_turn_delimiter_outputs": sum(features_by_line[row["_jsonl_line"]]["exact_turn_delimiter"] for row in rows),
        "turn_delimiter_or_prefix_outputs": sum(features_by_line[row["_jsonl_line"]]["turn_delimiter_or_prefix"] for row in rows),
        "ngram4_repeat_fraction": numeric_summary(features_by_line[row["_jsonl_line"]]["ngram4"]["repeat_fraction"] for row in rows),
        "ngram8_repeat_fraction": numeric_summary(features_by_line[row["_jsonl_line"]]["ngram8"]["repeat_fraction"] for row in rows),
    }


def group_pair_summary(pairs: list[dict[str, dict[str, Any]]], key_name: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for pair in pairs:
        value = pair["B2"][key_name]
        grouped[str(value)].append(pair)
    output: dict[str, Any] = {}
    for key, subset in sorted(grouped.items()):
        token_deltas = [p["B3"]["raw_token_count"] - p["B2"]["raw_token_count"] for p in subset]
        time_deltas = [p["B3"]["generation_seconds"] - p["B2"]["generation_seconds"] for p in subset]
        output[key] = {
            "pairs": len(subset),
            "finish_reason": {
                "B2": dict(sorted(Counter(p["B2"]["finish_reason"] for p in subset).items())),
                "B3": dict(sorted(Counter(p["B3"]["finish_reason"] for p in subset).items())),
            },
            "raw_token_count": {
                "B2": numeric_summary(p["B2"]["raw_token_count"] for p in subset),
                "B3": numeric_summary(p["B3"]["raw_token_count"] for p in subset),
                "B3_minus_B2": numeric_summary(token_deltas),
            },
            "generation_seconds": {
                "B2": numeric_summary(p["B2"]["generation_seconds"] for p in subset),
                "B3": numeric_summary(p["B3"]["generation_seconds"] for p in subset),
                "B3_minus_B2": numeric_summary(time_deltas),
            },
            "metrics": {metric: metric_pair_summary(subset, metric) for metric in ("parseable", "runnable", "target_valid", "oracle_bearing")},
        }
    return output


def validate_package(root: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    inventory_path = root / "INVENTORY.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    for item in inventory["packaged_files"]:
        relative = item["path"]
        path = root / relative
        if not path.is_file():
            errors.append(f"missing:{relative}")
            continue
        digest = sha256_file(path)
        hashes[relative] = digest
        if digest != item["sha256"]:
            errors.append(f"sha256:{relative}:got={digest}:expected={item['sha256']}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "inventory_schema_version": inventory.get("schema_version"),
        "immutable_packaged_file_sha256": dict(sorted(hashes.items())),
    }, errors


def analyze(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation, validation_errors = validate_package(root)
    paired_rows = load_jsonl(root / "evidence/b2_b3_paired.jsonl")
    b3_rows = load_jsonl(root / "evidence/b3_events.jsonl")

    by_baseline = {
        baseline: [row for row in paired_rows if row.get("baseline") == baseline]
        for baseline in ("B2", "B3")
    }
    features_by_baseline_line: dict[str, dict[int, dict[str, Any]]] = {"B2": {}, "B3": {}}
    for baseline, rows in by_baseline.items():
        for row in rows:
            features_by_baseline_line[baseline][row["_jsonl_line"]] = ending_features(row)

    pair_map: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in paired_rows:
        pair_map[row["task_id"]][row["baseline"]] = row
    complete_pairs = [pair for _, pair in sorted(pair_map.items()) if set(pair) == {"B2", "B3"}]
    prompt_mismatches = [
        pair["B2"]["task_id"]
        for pair in complete_pairs
        if pair["B2"]["prompt_sha256"] != pair["B3"]["prompt_sha256"]
    ]

    # Cross-check the dedicated B3 view by raw output hash and task id.
    b3_dedicated = {(row["task_id"], row["raw_output_sha256"]) for row in b3_rows}
    b3_paired = {(row["task_id"], row["raw_output_sha256"]) for row in by_baseline["B3"]}
    if b3_dedicated != b3_paired:
        validation_errors.append("dedicated_b3_view_mismatch")
        validation["status"] = "FAIL"

    b3_features: dict[int, dict[str, Any]] = {}
    cluster_rows: list[dict[str, Any]] = []
    for row in b3_rows:
        features = ending_features(row)
        b3_features[row["_jsonl_line"]] = features
        cluster_name = failure_cluster(row, features)
        cluster_rows.append({
            "jsonl_line": row["_jsonl_line"],
            "task_id": row["task_id"],
            "api_group": row["api_group"],
            "api": row["api"],
            "generation_seed": row["generation_seed"],
            "ab_order": row["ab_order"],
            "finish_reason": row["finish_reason"],
            "raw_token_count": row["raw_token_count"],
            "generation_seconds": row["generation_seconds"],
            "parseable": row["parseable"],
            "runnable": row["runnable"],
            "target_valid": row["target_valid"],
            "oracle_bearing": row["oracle_bearing"],
            "error_labels": ",".join(row.get("error_labels") or []) or "none",
            "failure_cluster": cluster_name,
            "exact_turn_delimiter": features["exact_turn_delimiter"],
            "turn_delimiter_or_prefix": features["turn_delimiter_or_prefix"],
            "end_of_turn_count": features["end_of_turn_count"],
            "start_of_turn_count": features["start_of_turn_count"],
            "role_sequence": features["role_sequence"],
            "unclosed_markdown_fence": features["unclosed_markdown_fence"],
            "unclosed_quote": features["unclosed_quote"],
            "unclosed_bracket_depth": features["unclosed_bracket_depth"],
            "unclosed_brackets": features["unclosed_brackets"],
            "unclosed_block_at_eof": features["unclosed_block_at_eof"],
            "compile_status": features["compile_status"],
            "repeated_suffix_block_tokens": features["repeated_suffix_block_tokens"],
            "repeated_suffix_repetitions": features["repeated_suffix_repetitions"],
            "ngram4_repeat_fraction": features["ngram4"]["repeat_fraction"],
            "ngram4_max_count": features["ngram4"]["max_count"],
            "ngram8_repeat_fraction": features["ngram8"]["repeat_fraction"],
            "ngram8_max_count": features["ngram8"]["max_count"],
            "output_chars": features["output_chars"],
            "output_lines": features["output_lines"],
            "prompt_echo_phrases": "|".join(features["prompt_echo_phrases"]),
            "raw_output_sha256": row["raw_output_sha256"],
            "ast_reason": row.get("ast_reason", ""),
        })

    b3_token_distribution = Counter(row["raw_token_count"] for row in b3_rows)
    role_sequences = Counter(b3_features[row["_jsonl_line"]]["role_sequence"] for row in b3_rows)
    prompt_echo_counts = {
        phrase: sum(phrase in b3_features[row["_jsonl_line"]]["prompt_echo_phrases"] for row in b3_rows)
        for phrase in PROMPT_ECHO_PHRASES
    }
    cluster_counts = Counter(row["failure_cluster"] for row in cluster_rows)

    same_api_similarity: dict[str, Any] = {}
    for baseline, rows in by_baseline.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["api"]].append(row)
        values = []
        for api_rows in grouped.values():
            if len(api_rows) == 2:
                values.append(jaccard(shingle_set(api_rows[0]["raw_output"]), shingle_set(api_rows[1]["raw_output"])))
        same_api_similarity[baseline] = numeric_summary(values)

    pair_token_deltas = [pair["B3"]["raw_token_count"] - pair["B2"]["raw_token_count"] for pair in complete_pairs]
    pair_time_deltas = [pair["B3"]["generation_seconds"] - pair["B2"]["generation_seconds"] for pair in complete_pairs]
    paired_output_similarity = [
        jaccard(shingle_set(pair["B2"]["raw_output"]), shingle_set(pair["B3"]["raw_output"]))
        for pair in complete_pairs
    ]

    seed_to_orders: dict[str, list[str]] = defaultdict(list)
    for pair in complete_pairs:
        seed_to_orders[str(pair["B2"]["generation_seed"])].append(pair["B2"]["ab_order"])
    seed_order_map = {seed: sorted(set(orders)) for seed, orders in sorted(seed_to_orders.items())}
    order_identifiable = all(len(orders) > 1 for orders in seed_order_map.values())

    manifests = {
        "3407": json.loads((root / "evidence/run_manifest_seed3407.json").read_text(encoding="utf-8")),
        "7711": json.loads((root / "evidence/run_manifest_seed7711.json").read_text(encoding="utf-8")),
    }
    runner_path = root / "runner/frozen_notebook_code.py"
    runner_text = runner_path.read_text(encoding="utf-8")

    diagnostics: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "claim_boundary": {
            "diagnoses": "observed B3 artifact/harness outputs in two complete generation seeds",
            "does_not_prove": [
                "defect in unavailable GGUF weights",
                "tokenizer metadata defect",
                "merge or conversion defect",
                "quantization damage",
                "training-run collapse",
                "behavior of fine-tuned models generally",
            ],
            "checkpoint": "two seeds (3407 and 7711), not the planned five-seed final campaign",
        },
        "validation": {
            **validation,
            "errors": validation_errors,
            "validator_pass_block_recomputed": {
                "status": "PASS" if not validation_errors else "FAIL",
                "b3_events": len(b3_rows),
                "paired_events": len(paired_rows),
                "complete_pairs": len(complete_pairs),
                "prompt_mismatches": len(prompt_mismatches),
                "b3_finish_reason_length": sum(row["finish_reason"] == "length" for row in b3_rows),
                "b3_parseable": sum(bool(row["parseable"]) for row in b3_rows),
                "b3_runnable": sum(bool(row["runnable"]) for row in b3_rows),
                "b3_target_valid": sum(bool(row["target_valid"]) for row in b3_rows),
                "b3_oracle_bearing": sum(bool(row["oracle_bearing"]) for row in b3_rows),
            },
        },
        "pairing": {
            "paired_events": len(paired_rows),
            "complete_pairs": len(complete_pairs),
            "baseline_counts": dict(sorted(Counter(row["baseline"] for row in paired_rows).items())),
            "prompt_mismatch_count": len(prompt_mismatches),
            "prompt_mismatch_task_ids": prompt_mismatches,
            "generation_seed_counts_b3": dict(sorted(Counter(str(row["generation_seed"]) for row in b3_rows).items())),
            "dedicated_b3_view_matches_paired_view": b3_dedicated == b3_paired,
        },
        "baseline_summary": {
            baseline: summarize_baseline(rows, features_by_baseline_line[baseline])
            for baseline, rows in by_baseline.items()
        },
        "b3_token_ceiling": {
            "declared_max_tokens": manifests["3407"]["decoding"]["max_tokens"],
            "finish_reason_length": sum(row["finish_reason"] == "length" for row in b3_rows),
            "retokenized_raw_token_count_distribution": {str(k): v for k, v in sorted(b3_token_distribution.items())},
            "retokenized_count_within_3_of_declared_ceiling": sum(abs(row["raw_token_count"] - manifests["3407"]["decoding"]["max_tokens"]) <= 3 for row in b3_rows),
            "interpretation": "finish_reason is response telemetry; raw_token_count is a post-hoc retokenization of decoded text and is not the API usage completion-token field",
        },
        "b3_endings_and_structure": {
            "exact_turn_delimiter_outputs": sum(features["exact_turn_delimiter"] for features in b3_features.values()),
            "turn_delimiter_or_truncated_prefix_outputs": sum(features["turn_delimiter_or_prefix"] for features in b3_features.values()),
            "total_end_of_turn_markers": sum(features["end_of_turn_count"] for features in b3_features.values()),
            "total_start_of_turn_markers": sum(features["start_of_turn_count"] for features in b3_features.values()),
            "unclosed_markdown_fence_outputs": sum(features["unclosed_markdown_fence"] for features in b3_features.values()),
            "unclosed_quote_outputs": sum(features["unclosed_quote"] for features in b3_features.values()),
            "unclosed_bracket_outputs": sum(features["unclosed_bracket_depth"] > 0 for features in b3_features.values()),
            "unclosed_block_at_eof_outputs": sum(features["unclosed_block_at_eof"] for features in b3_features.values()),
            "compile_status": dict(sorted(Counter(features["compile_status"] for features in b3_features.values()).items())),
            "immediate_repeated_suffix_outputs": sum(features["repeated_suffix_repetitions"] >= 2 for features in b3_features.values()),
            "role_sequences": dict(sorted(role_sequences.items(), key=lambda item: (-item[1], item[0]))),
            "prompt_echo_phrase_outputs": prompt_echo_counts,
            "failure_cluster_counts": dict(sorted(cluster_counts.items(), key=lambda item: (-item[1], item[0]))),
        },
        "repetition_and_template_collapse": {
            "unique_output_hashes": {
                baseline: len({row["raw_output_sha256"] for row in rows})
                for baseline, rows in by_baseline.items()
            },
            "ngram4_repeat_fraction": {
                baseline: numeric_summary(features_by_baseline_line[baseline][row["_jsonl_line"]]["ngram4"]["repeat_fraction"] for row in rows)
                for baseline, rows in by_baseline.items()
            },
            "ngram8_repeat_fraction": {
                baseline: numeric_summary(features_by_baseline_line[baseline][row["_jsonl_line"]]["ngram8"]["repeat_fraction"] for row in rows)
                for baseline, rows in by_baseline.items()
            },
            "cross_api_5gram_jaccard": {
                baseline: cross_api_similarity(rows) for baseline, rows in by_baseline.items()
            },
            "same_api_cross_seed_5gram_jaccard": same_api_similarity,
            "paired_b2_b3_same_prompt_5gram_jaccard": numeric_summary(paired_output_similarity),
        },
        "pairwise": {
            "overall_metrics": {metric: metric_pair_summary(complete_pairs, metric) for metric in ("parseable", "runnable", "target_valid", "oracle_bearing")},
            "raw_token_count_B3_minus_B2": numeric_summary(pair_token_deltas),
            "generation_seconds_B3_minus_B2": numeric_summary(pair_time_deltas),
            "pairs_where_B3_slower": sum(delta > 0 for delta in pair_time_deltas),
            "by_seed": group_pair_summary(complete_pairs, "generation_seed"),
            "by_api_group": group_pair_summary(complete_pairs, "api_group"),
            "by_ab_order": group_pair_summary(complete_pairs, "ab_order"),
            "order_identifiability": {
                "seed_to_observed_orders": seed_order_map,
                "order_effect_identifiable_within_seed": order_identifiable,
                "conclusion": "A/B order is perfectly confounded with seed in this two-seed checkpoint; an order effect cannot be separated from a seed effect.",
            },
        },
        "runner_audit": {
            "file": "runner/frozen_notebook_code.py",
            "sha256": sha256_file(runner_path),
            "llama_cpp_python_version": manifests["3407"]["packages"]["llama-cpp-python"],
            "n_ctx_declared_in_frozen_code": 2048 if "N_CTX = 2048" in runner_text else None,
            "max_tokens_declared_in_manifests": manifests["3407"]["decoding"]["max_tokens"],
            "primary_path": "llm.create_chat_completion(messages=messages, **common)",
            "fallback_path": "llm(manual_gemma_prompt(messages), stop=['<end_of_turn>', '<start_of_turn>'], echo=False, **common)",
            "primary_path_has_explicit_turn_stop_strings": "create_chat_completion(messages=messages, stop=" in runner_text,
            "fallback_has_explicit_turn_stop_strings": "stop=['<end_of_turn>', '<start_of_turn>']" in runner_text,
            "event_records_generation_branch": False,
            "branch_inference": {
                "events_with_exact_turn_delimiters": sum(features["exact_turn_delimiter"] for features in b3_features.values()),
                "inference": "Those outputs are inconsistent with the fallback's explicit text stops operating normally, so they strongly indicate the primary create_chat_completion path. Marker-free outputs remain branch-ambiguous because no branch field was logged.",
            },
            "manual_prompt_roles": "assistant is mapped to model; system is emitted literally as system",
            "extraction": "first complete markdown fence if present, otherwise trims leading text before the first 'import '; it does not remove later chat-turn text",
            "effective_load_attempts": "not recorded per event; code tries (2048,-1), (2048,60), (2048,48), (1536,40), (1024,32)",
            "gguf_chat_template_metadata": "not present in uploaded evidence; unavailable GGUF is required to inspect tokenizer.chat_template and token ids",
        },
        "ranked_hypotheses": [
            {
                "rank": 1,
                "hypothesis": "max-token exhaustion is the immediate termination mechanism",
                "label": "directly_supported",
                "basis": "240/240 B3 finish_reason=length and every post-hoc raw count is 599-603 around max_tokens=600; many outputs end in unfinished syntax or a truncated turn-token prefix.",
                "boundary": "This does not explain why B3 keeps generating; B2 also frequently reaches the same cap while retaining far higher validity.",
            },
            {
                "rank": 2,
                "hypothesis": "repetitive/collapsed multi-turn output behavior",
                "label": "directly_supported",
                "basis": "B3 has turn-delimiter/prefix leakage in 232/240 outputs, prompt echoes, repeated role cycles, and substantially higher within-output n-gram repetition than B2.",
                "boundary": "This is an output phenotype, not proof of a training or weight defect.",
            },
            {
                "rank": 3,
                "hypothesis": "chat-template, stop-token, or EOS mismatch for the tuned artifact on the primary chat path",
                "label": "plausible_but_unverified",
                "basis": "Gemma turn delimiters are emitted as text and generation continues into synthetic user/model turns; the primary path supplied no explicit turn stops, while the fallback did.",
                "boundary": "The GGUF tokenizer/chat-template metadata, emitted token ids, and selected chat handler were not recorded and the GGUF is absent.",
            },
            {
                "rank": 4,
                "hypothesis": "GGUF conversion or merge mismatch",
                "label": "plausible_but_unverified",
                "basis": "An artifact-specific metadata/token-id mismatch could produce the observed delimiter behavior.",
                "boundary": "No source weights, merge logs, conversion command, or GGUF metadata are available.",
            },
            {
                "rank": 5,
                "hypothesis": "quantization damage",
                "label": "not_supported",
                "basis": "No higher-precision tuned control or pre-quantized tuned model is supplied; the working B2 control is also Q3_K_M, so quantization level alone is not an observed discriminator.",
                "boundary": "Artifact-specific quantization damage is not ruled out, only unsupported here.",
            },
            {
                "rank": 6,
                "hypothesis": "training collapse",
                "label": "not_supported",
                "basis": "The output is collapsed, but no training curves, checkpoints, adapter, tokenizer, or pre-GGUF inference are supplied.",
                "boundary": "Do not convert an observed output phenotype into a training-quality conclusion.",
            },
        ],
        "source_json_pointers": {
            "max_tokens": [
                "evidence/run_manifest_seed3407.json#/decoding/max_tokens",
                "evidence/run_manifest_seed7711.json#/decoding/max_tokens",
            ],
            "llama_cpp_version": [
                "evidence/run_manifest_seed3407.json#/packages/llama-cpp-python",
                "evidence/run_manifest_seed7711.json#/packages/llama-cpp-python",
            ],
            "tuned_artifact": [
                "evidence/run_manifest_seed3407.json#/tuned_model",
                "evidence/run_manifest_seed7711.json#/tuned_model",
            ],
            "event_fields": "evidence/b3_events.jsonl#/<line>/{finish_reason,raw_token_count,raw_output,parseable,runnable,target_valid,oracle_bearing}",
        },
    }
    return diagnostics, cluster_rows


def write_clusters(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--clusters-out", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.package_root.resolve()
    json_out = args.json_out or (root / "b3_diagnostics.json")
    clusters_out = args.clusters_out or (root / "b3_failure_clusters.csv")
    diagnostics, clusters = analyze(root)
    json_out.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_clusters(clusters_out, clusters)
    print(json.dumps({
        "status": diagnostics["validation"]["status"],
        "json_out": str(json_out),
        "clusters_out": str(clusters_out),
        "b3_events": diagnostics["validation"]["validator_pass_block_recomputed"]["b3_events"],
        "complete_pairs": diagnostics["pairing"]["complete_pairs"],
    }, sort_keys=True))
    return 0 if diagnostics["validation"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
