#!/usr/bin/env python3
"""Deterministic, same-corpus replay for TrDGL-FuzzVn component ablations.

The script never generates programs.  It re-evaluates a frozen JSONL event corpus
under full, no-AST, no-oracle, no-Vn, and no-Atlas policies.  Fine-tuning is
handled separately: B2/B3 records are checked for paired API/seed/prompt inputs,
because removing fine-tuning requires regeneration rather than gate replay.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


POLICY_VERSION = "trdgl_ablation_replay_v1"
CONDITIONS = ("full", "no_ast", "no_oracle", "no_vn", "no_atlas")
EVIDENCE_LABELS = ("validation_only", "diagnostic_checkpoint", "paper_candidate")
STAGES = (
    "raw",
    "parseable",
    "ast_pass",
    "runnable",
    "target_valid",
    "oracle_bearing",
    "reproducible",
    "non_duplicate",
    "minimized",
    "stable_nightly_known",
    "promoted_counterfactual",
)
UNKNOWN_STATUS = {"", "pending", "unknown", "unrun", "not_run", "na", "n/a", "none", "null"}
ALLOWED_IMPORT_ROOTS = {"torch", "math", "numpy", "typing"}
UNSAFE_IMPORT_ROOTS = {"os", "sys", "subprocess", "socket", "requests", "ctypes", "multiprocessing"}
BANNED_CALL_ROOTS = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "os", "sys", "subprocess", "socket", "requests", "ctypes", "multiprocessing",
}

# Three-valued logic: True/False are evidence; None is explicitly pending.
Tri = Optional[bool]


def tri_and(*values: Tri) -> Tri:
    if any(value is False for value in values):
        return False
    if any(value is None for value in values):
        return None
    return True


def tri_not(value: Tri) -> Tri:
    return None if value is None else not value


def as_tri(value: Any) -> Tri:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return None
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "pass", "passed", "ok", "success"}:
        return True
    if text in {"false", "no", "n", "0", "fail", "failed", "error"}:
        return False
    if text in UNKNOWN_STATUS:
        return None
    raise ValueError(f"Cannot interpret tri-state value: {value!r}")


def first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


@dataclass(frozen=True)
class StaticResult:
    parseable: bool
    safety_pass: bool
    ast_policy_pass: bool
    target_call_present: bool
    oracle_present: bool
    fake_assertion: bool
    reasons: tuple[str, ...]


def inspect_code(code: str, target_api: str) -> StaticResult:
    """Apply one frozen AST policy to every condition and every record.

    The immutable safety screen remains enabled for no_ast. The ablated AST
    policy consists of the import allow-list, broad-exception suppression, and
    the 20 KiB size rule. Exact target-call validation remains a later, separate
    funnel stage. This distinction prevents an ablation from granting generated
    code file/network/process access on the experiment host.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, TypeError) as exc:
        return StaticResult(False, False, False, False, False, False, (f"syntax:{exc}",))

    safety_reasons: list[str] = []
    quality_reasons: list[str] = []
    call_names: list[str] = []
    oracle_present = False
    fake_assertion = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in UNSAFE_IMPORT_ROOTS:
                    safety_reasons.append(f"unsafe_import:{alias.name}")
                elif root not in ALLOWED_IMPORT_ROOTS:
                    quality_reasons.append(f"disallowed_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in UNSAFE_IMPORT_ROOTS:
                safety_reasons.append(f"unsafe_import_from:{node.module}")
            elif root not in ALLOWED_IMPORT_ROOTS:
                quality_reasons.append(f"disallowed_import_from:{node.module}")
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            call_names.append(name)
            if name.split(".")[0] in BANNED_CALL_ROOTS:
                safety_reasons.append(f"unsafe_call:{name}")
            if name in {"torch.testing.assert_close", "numpy.testing.assert_allclose", "numpy.testing.assert_equal"}:
                call_is_fake = len(node.args) >= 2 and ast.dump(node.args[0]) == ast.dump(node.args[1])
                fake_assertion = fake_assertion or call_is_fake
                oracle_present = oracle_present or not call_is_fake
        elif isinstance(node, ast.Assert):
            test = node.test
            is_fake = isinstance(test, ast.Constant)
            if isinstance(test, ast.Compare) and len(test.comparators) == 1:
                is_fake = is_fake or ast.dump(test.left) == ast.dump(test.comparators[0])
            for child in ast.walk(test):
                if isinstance(child, ast.Call) and dotted_name(child.func).endswith(("allclose", "isclose")) and len(child.args) >= 2:
                    is_fake = is_fake or ast.dump(child.args[0]) == ast.dump(child.args[1])
            fake_assertion = fake_assertion or is_fake
            oracle_present = oracle_present or not is_fake
        elif isinstance(node, ast.ExceptHandler):
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})
            suppresses = not any(isinstance(child, ast.Raise) for stmt in node.body for child in ast.walk(stmt))
            if broad and suppresses:
                quality_reasons.append("suppressed_broad_exception")

    target_present = target_api in call_names
    if len(code.encode("utf-8")) > 20_000:
        quality_reasons.append("program_over_20k")
    safety_pass = not safety_reasons
    ast_policy_pass = safety_pass and not quality_reasons
    return StaticResult(
        True, safety_pass, ast_policy_pass, target_present, oracle_present,
        fake_assertion, tuple(sorted(set(safety_reasons + quality_reasons))),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: event must be an object")
            row["_source_line"] = line_number
            rows.append(row)
    return rows


def event_id(row: dict[str, Any]) -> str:
    explicit = first(row, "event_id", "task_id", "generation_id")
    baseline = str(row.get("baseline", "unknown"))
    if explicit is not None:
        return f"{baseline}:{explicit}"
    api = first(row, "api", "target_api")
    seed = first(row, "generation_seed", "seed", "decoding_seed")
    if api is None or seed is None:
        raise ValueError(f"line {row.get('_source_line')}: needs event/task ID or API plus generation seed")
    return f"{baseline}:{api}:{seed}"


def event_code(row: dict[str, Any]) -> str:
    value = first(row, "extracted_code", "code", "raw_output")
    if value is None:
        raise ValueError(f"line {row.get('_source_line')}: missing extracted_code/code/raw_output")
    return str(value)


def event_raw_hash(row: dict[str, Any], verify: bool = True) -> str:
    raw = first(row, "raw_output", "extracted_code", "code")
    if raw is None:
        raise ValueError(f"line {row.get('_source_line')}: missing raw_output/extracted_code/code")
    actual = sha256_text(str(raw))
    recorded = first(row, "raw_output_sha256", "raw_output_hash")
    if verify and recorded not in (None, "") and str(recorded).lower() != actual:
        raise ValueError(
            f"line {row.get('_source_line')}: raw-output SHA-256 mismatch "
            f"(recorded {recorded}, actual {actual})"
        )
    return actual


def decoding_seed_verified(row: dict[str, Any]) -> bool:
    explicit = first(row, "decoding_seed_applied", "sampler_seed_applied")
    if explicit is not None:
        return as_tri(explicit) is True
    backend = str(first(row, "seed_backend", "seed_evidence") or "").lower()
    if str(row.get("baseline", "")) == "B0":
        return "template" in backend
    return "completion(seed)" in backend or "sampler" in backend and "seed" in backend


def status_known(value: Any) -> Tri:
    if value is None:
        return None
    if str(value).strip().lower() in UNKNOWN_STATUS:
        return None
    return True


def normalize_fingerprint(value: Any) -> str:
    text = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", str(value or ""))
    text = re.sub(r"\b\d+\b", "<N>", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def load_atlas(path: Optional[Path]) -> dict[str, str]:
    if path is None:
        return {}
    mapping: dict[str, str] = {}
    for row in read_jsonl(path):
        fingerprint = first(row, "fingerprint", "candidate_fingerprint", "failure_signature", "signature")
        cluster = first(row, "cluster_id", "duplicate_cluster", "canonical_cluster")
        if fingerprint is None or cluster is None:
            raise ValueError(f"Atlas line {row.get('_source_line')} lacks fingerprint or cluster ID")
        key = normalize_fingerprint(fingerprint)
        if key and key in mapping and mapping[key] != str(cluster):
            raise ValueError(f"Atlas fingerprint maps to conflicting clusters: {fingerprint!r}")
        mapping[key] = str(cluster)
    return mapping


def duplicate_evidence(row: dict[str, Any], atlas: dict[str, str], atlas_supplied: bool) -> tuple[Tri, Optional[str], Tri]:
    """Return (is_duplicate, cluster, atlas_checked)."""
    fingerprint = first(row, "candidate_fingerprint", "failure_signature", "signature")
    if atlas_supplied:
        key = normalize_fingerprint(fingerprint)
        cluster = atlas.get(key) if key else None
        return cluster is not None, cluster, True

    explicit_duplicate = first(row, "atlas_duplicate", "is_duplicate", "duplicate")
    cluster = first(row, "duplicate_cluster", "nearest_atlas_cluster")
    checked = as_tri(first(row, "atlas_checked", "duplicate_checked"))
    if explicit_duplicate is not None:
        return as_tri(explicit_duplicate), str(cluster) if cluster not in (None, "") else None, True
    if cluster not in (None, "", "none", "null"):
        return True, str(cluster), True
    if checked is True:
        return False, None, True
    # Both an absent flag and atlas_checked=false mean the search is unfinished.
    return None, None, None


def replay_one(row: dict[str, Any], condition: str, atlas: dict[str, str], atlas_supplied: bool) -> dict[str, Any]:
    code = event_code(row)
    api = str(first(row, "api", "target_api") or "")
    static = inspect_code(code, api)

    # Execution is measured once by the common harness, never re-run per condition.
    runnable = as_tri(first(row, "runnable", "execution_pass"))
    if runnable is None:
        exit_code = first(row, "exit_code", "subprocess_exit", "subprocess_exit_code")
        timed_out = as_tri(first(row, "timeout", "timed_out"))
        if exit_code is not None and timed_out is not None:
            runnable = int(exit_code) == 0 and not timed_out

    ast_gate: Tri = static.safety_pass if condition == "no_ast" else static.ast_policy_pass
    target_valid = tri_and(static.parseable, ast_gate, runnable, static.target_call_present)
    oracle_observed = tri_and(static.oracle_present, not static.fake_assertion)
    oracle_gate = True if condition == "no_oracle" else oracle_observed
    oracle_stage = tri_and(target_valid, oracle_gate)

    anomaly = as_tri(first(row, "anomaly_triggered", "anomaly", "oracle_triggered", "candidate_triggered"))
    reproduced = as_tri(first(row, "reproduced", "reproducible"))
    reproducible_observed = tri_and(oracle_stage, anomaly, reproduced)
    reproducible_gate = oracle_stage if condition == "no_vn" else reproducible_observed

    is_duplicate, cluster, atlas_checked = duplicate_evidence(row, atlas, atlas_supplied)
    non_duplicate_observed = tri_and(atlas_checked, tri_not(is_duplicate))
    non_duplicate_gate = reproducible_gate if condition == "no_atlas" else tri_and(reproducible_gate, non_duplicate_observed)

    minimized = as_tri(first(row, "minimized", "is_minimized"))
    minimized_gate = non_duplicate_gate if condition == "no_vn" else tri_and(non_duplicate_gate, minimized)

    stable_known = status_known(first(row, "stable_status", "stable"))
    nightly_known = status_known(first(row, "nightly_status", "nightly", "main_status"))
    versions_known = tri_and(stable_known, nightly_known)
    versions_gate = minimized_gate if condition == "no_vn" else tri_and(minimized_gate, versions_known)

    stages: dict[str, Tri] = {
        "raw": True,
        "parseable": static.parseable,
        "ast_pass": tri_and(static.parseable, ast_gate),
        "runnable": tri_and(static.parseable, ast_gate, runnable),
        "target_valid": target_valid,
        "oracle_bearing": oracle_stage,
        "reproducible": reproducible_gate,
        "non_duplicate": non_duplicate_gate,
        "minimized": minimized_gate,
        "stable_nightly_known": versions_gate,
        "promoted_counterfactual": versions_gate,
    }
    return {
        "event_id": event_id(row),
        "condition": condition,
        "baseline": row.get("baseline"),
        "api": api,
        "generation_seed": first(row, "generation_seed", "seed", "decoding_seed"),
        "raw_output_sha256": event_raw_hash(row),
        "extracted_code_sha256": sha256_text(code),
        "static": {
            "safety_pass": static.safety_pass,
            "observed_ast_policy_pass": static.ast_policy_pass,
            "target_call_present": static.target_call_present,
            "oracle_present": static.oracle_present,
            "fake_assertion": static.fake_assertion,
            "reasons": list(static.reasons),
        },
        "candidate": {
            "anomaly_triggered": anomaly,
            "reproduced": reproduced,
            "atlas_checked": atlas_checked,
            "is_duplicate": is_duplicate,
            "duplicate_cluster": cluster,
            "minimized": minimized,
            "stable_nightly_known": versions_known,
        },
        "stages": stages,
    }


def corpus_hash(rows: Iterable[dict[str, Any]]) -> str:
    items = sorted(
        (
            event_id(row), event_raw_hash(row), sha256_text(event_code(row)),
            first(row, "generation_seed", "seed", "decoding_seed"),
        )
        for row in rows
    )
    return sha256_text(canonical_json(items))


def summarize(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        subset = [row for row in decisions if row["condition"] == condition]
        total = len(subset)
        for stage in STAGES:
            counts = Counter("pending" if row["stages"][stage] is None else "pass" if row["stages"][stage] else "fail" for row in subset)
            known = counts["pass"] + counts["fail"]
            output.append({
                "condition": condition,
                "stage": stage,
                "n_raw": total,
                "n_pass": counts["pass"],
                "n_fail": counts["fail"],
                "n_pending": counts["pending"],
                "rate_among_known": round(counts["pass"] / known, 6) if known else None,
                "rate_per_raw": round(counts["pass"] / total, 6) if total else None,
            })
    return output


def validate_same_corpus(decisions: list[dict[str, Any]]) -> None:
    expected: Optional[set[tuple[str, str]]] = None
    for condition in CONDITIONS:
        keys = {
            (
                row["event_id"], row["raw_output_sha256"],
                row["extracted_code_sha256"], row["generation_seed"],
            )
            for row in decisions if row["condition"] == condition
        }
        if expected is None:
            expected = keys
        elif keys != expected:
            raise AssertionError(f"Condition {condition} did not replay the identical raw corpus")


def condition_corpus_hashes(decisions: list[dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for condition in CONDITIONS:
        items = sorted(
            (
                row["event_id"], row["raw_output_sha256"],
                row["extracted_code_sha256"], row["generation_seed"],
            )
            for row in decisions if row["condition"] == condition
        )
        hashes[condition] = sha256_text(canonical_json(items))
    return hashes


def fine_tuning_pairs(all_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_key: dict[tuple[str, Any], dict[str, dict[str, Any]]] = {}
    for row in all_rows:
        baseline = str(row.get("baseline", ""))
        if baseline not in {"B2", "B3"}:
            continue
        api = str(first(row, "api", "target_api") or "")
        seed = first(row, "generation_seed", "seed", "decoding_seed")
        members = by_key.setdefault((api, seed), {})
        if baseline in members:
            raise ValueError(f"Duplicate {baseline} record for fine-tuning pair key {(api, seed)!r}")
        members[baseline] = row

    pairs: list[dict[str, Any]] = []
    missing = 0
    prompt_mismatch = 0
    for (api, seed), members in sorted(by_key.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        b2, b3 = members.get("B2"), members.get("B3")
        paired = b2 is not None and b3 is not None
        if not paired:
            missing += 1
        b2_prompt = first(b2 or {}, "prompt_sha256", "prompt_hash")
        b3_prompt = first(b3 or {}, "prompt_sha256", "prompt_hash")
        prompt_equal: Tri = None if not paired or b2_prompt is None or b3_prompt is None else b2_prompt == b3_prompt
        if prompt_equal is False:
            prompt_mismatch += 1
        pairs.append({
            "api": api,
            "generation_seed": seed,
            "has_b2": b2 is not None,
            "has_b3": b3 is not None,
            "same_prompt_hash": prompt_equal,
            "b2_event_id": event_id(b2) if b2 else None,
            "b3_event_id": event_id(b3) if b3 else None,
        })
    report = {
        "method": "paired B2 base+full-prompt versus B3 tuned+same-full-prompt",
        "regeneration_required": True,
        "reason": "Fine-tuning changes generated programs; it is not a downstream gate and cannot be replayed from frozen B3 outputs.",
        "pair_keys_seen": len(pairs),
        "complete_pairs": sum(row["has_b2"] and row["has_b3"] for row in pairs),
        "incomplete_pairs": missing,
        "prompt_hash_mismatches": prompt_mismatch,
        "complete_same_prompt_pairs": sum(
            row["has_b2"] and row["has_b3"] and row["same_prompt_hash"] is True for row in pairs
        ),
    }
    report["fair_comparison_ready"] = bool(pairs) and report["complete_same_prompt_pairs"] == len(pairs)
    return pairs, report


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_latex(path: Path, summary: list[dict[str, Any]], evidence_label: str) -> None:
    indexed = {(row["condition"], row["stage"]): row for row in summary}
    labels = {"full": "Full", "no_ast": "No AST", "no_oracle": "No oracle", "no_vn": "No Vn", "no_atlas": "No Atlas"}
    displayed_stages = (
        "raw", "ast_pass", "runnable", "target_valid", "oracle_bearing",
        "reproducible", "non_duplicate", "minimized", "stable_nightly_known",
        "promoted_counterfactual",
    )
    caption_prefix = {
        "validation_only": "Validation-only smoke (not a research result). ",
        "diagnostic_checkpoint": "Diagnostic campaign checkpoint (not a final research result). ",
        "paper_candidate": "",
    }[evidence_label]
    lines = [
        "% Generated by replay_ablation.py; counterfactual eligibility is not a confirmed bug count.",
        f"% Evidence label: {evidence_label}",
        "\\begin{table*}[t]",
        "\\centering",
        f"\\caption{{{caption_prefix}Same-corpus component ablation. Entries are condition-specific gate-pass counts (a disabled gate passes through the preceding eligible set); Pending is the final-stage unknown count. Eligibility is counterfactual and is not a confirmed bug count.}}",
        "\\label{tab:ablation_replay}",
        "\\resizebox{\\textwidth}{!}{%",
        "\\begin{tabular}{lrrrrrrrrrrr}",
        "\\toprule",
        "Condition & Raw & AST gate & Run & Target & Oracle gate & Reprod. & Nondup. & Min. & Status & Eligible & Pending \\\\",
        "\\midrule",
    ]
    for condition in CONDITIONS:
        values = [indexed[(condition, stage)]["n_pass"] for stage in displayed_stages]
        pending = indexed[(condition, "promoted_counterfactual")]["n_pending"]
        lines.append(f"{labels[condition]} & " + " & ".join(str(value) for value in values) + f" & {pending} \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}%", "}", "\\end{table*}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    events_path: Path,
    output_dir: Path,
    baseline: str,
    atlas_path: Optional[Path],
    run_signature: Optional[str] = None,
    evidence_label: str = "validation_only",
) -> dict[str, Any]:
    if evidence_label not in EVIDENCE_LABELS:
        raise ValueError(f"Unsupported evidence label: {evidence_label!r}")
    all_rows = read_jsonl(events_path)
    signatures = sorted({str(row["run_signature"]) for row in all_rows if row.get("run_signature") not in (None, "")})
    if run_signature is None and len(signatures) > 1:
        raise ValueError(f"Multiple run signatures found; choose one with --run-signature: {signatures}")
    effective_signature = run_signature or (signatures[0] if signatures else None)
    run_rows = [row for row in all_rows if effective_signature is None or str(row.get("run_signature")) == effective_signature]
    if run_signature is not None and not run_rows:
        raise ValueError(f"No records found for run signature {run_signature!r}")
    selected = run_rows if baseline == "ALL" else [row for row in run_rows if row.get("baseline") == baseline]
    if not selected:
        raise ValueError(f"No records selected for baseline {baseline!r}")
    ids = [event_id(row) for row in selected]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate event IDs in frozen corpus: {duplicates[:5]}")
    missing_seed = [event_id(row) for row in selected if first(row, "generation_seed", "seed", "decoding_seed") is None]
    if missing_seed:
        raise ValueError(f"Every replay record needs the true decoding seed; missing: {missing_seed[:5]}")
    unverified_seed = [event_id(row) for row in selected if not decoding_seed_verified(row)]
    if unverified_seed:
        raise ValueError(
            "Generation-seed values exist but sampler plumbing is unverified; "
            f"need decoding_seed_applied=true or seed_backend evidence: {unverified_seed[:5]}"
        )

    atlas = load_atlas(atlas_path)
    decisions = [replay_one(row, condition, atlas, atlas_path is not None) for condition in CONDITIONS for row in selected]
    validate_same_corpus(decisions)
    replay_hashes = condition_corpus_hashes(decisions)
    if len(set(replay_hashes.values())) != 1:
        raise AssertionError(f"Fairness failure: condition corpus hashes differ: {replay_hashes}")
    frozen_corpus_hash = corpus_hash(selected)
    if set(replay_hashes.values()) != {frozen_corpus_hash}:
        raise AssertionError("Fairness failure: replay hashes differ from the frozen input corpus hash")
    summary = summarize(decisions)
    pairs, pair_report = fine_tuning_pairs(run_rows)
    for row in decisions:
        row["evidence_label"] = evidence_label
    for row in summary:
        row["evidence_label"] = evidence_label
    for row in pairs:
        row["evidence_label"] = evidence_label

    output_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = output_dir / "ablation_decisions.jsonl"
    with decisions_path.open("w", encoding="utf-8") as handle:
        for row in decisions:
            handle.write(canonical_json(row) + "\n")
    write_csv(output_dir / "ablation_summary.csv", summary)
    write_csv(output_dir / "fine_tuning_pairs.csv", pairs)
    write_latex(output_dir / "ablation_table.tex", summary, evidence_label)

    manifest = {
        "policy_version": POLICY_VERSION,
        "replay_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evidence_label": evidence_label,
        "events_path": str(events_path.resolve()),
        "events_file_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
        "run_signature": effective_signature,
        "baseline_replayed": baseline,
        "raw_event_count": len(selected),
        "decoding_seed_evidence_complete": True,
        "corpus_sha256": frozen_corpus_hash,
        "condition_corpus_sha256": replay_hashes,
        "condition_event_counts": {
            condition: sum(row["condition"] == condition for row in decisions) for condition in CONDITIONS
        },
        "conditions": list(CONDITIONS),
        "same_corpus_verified": True,
        "atlas_path": str(atlas_path.resolve()) if atlas_path else None,
        "atlas_sha256": hashlib.sha256(atlas_path.read_bytes()).hexdigest() if atlas_path else None,
        "pending_semantics": "Missing triage fields are pending, never false or zero.",
        "promotion_semantics": "promoted_counterfactual means gate eligibility under that condition, not a confirmed framework bug.",
        "atlas_planning_ablation": {
            "regeneration_required": True,
            "reason": "Atlas-guided surface planning changes generation inputs; same-corpus no_atlas isolates duplicate triage only.",
        },
        "fine_tuning_ablation": pair_report,
    }
    (output_dir / "ablation_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def self_test() -> None:
    import tempfile

    prompt_hash = sha256_text("same full prompt")
    common = {
        "api": "torch.add", "generation_seed": 3407, "runnable": True,
        "seed_backend": "host+torch+cuda+llama_cpp.set_seed+completion(seed)",
        "anomaly_triggered": True, "reproduced": True, "minimized": True,
        "atlas_checked": True, "is_duplicate": False,
        "stable_status": "reproduced", "nightly_status": "not_affected",
        "prompt_sha256": prompt_hash,
    }
    rows = [
        {**common, "baseline": "B3", "task_id": "good", "extracted_code": "import torch\nx=torch.add(torch.tensor(1),torch.tensor(2))\nassert x.item()==3\n"},
        {**common, "baseline": "B3", "task_id": "ast", "generation_seed": 7711, "extracted_code": "import torch\ntry:\n x=torch.add(torch.tensor(1),torch.tensor(2))\nexcept Exception:\n pass\nassert x.item()==3\n"},
        {**common, "baseline": "B3", "task_id": "dup", "generation_seed": 12011, "is_duplicate": True, "duplicate_cluster": "C1", "extracted_code": "import torch\nx=torch.add(torch.tensor(1),torch.tensor(2))\nassert x.item()==3\n"},
        {**common, "baseline": "B3", "task_id": "pending", "generation_seed": 19001, "reproduced": None, "minimized": None, "atlas_checked": None, "is_duplicate": None, "stable_status": "pending", "nightly_status": "pending", "extracted_code": "import torch\nx=torch.add(torch.tensor(1),torch.tensor(2))\nassert x.item()==3\n"},
        {**common, "baseline": "B3", "task_id": "vn", "generation_seed": 27103, "reproduced": False, "minimized": False, "stable_status": "pending", "nightly_status": "pending", "extracted_code": "import torch\nx=torch.add(torch.tensor(1),torch.tensor(2))\nassert x.item()==3\n"},
        {**common, "baseline": "B2", "task_id": "pair", "extracted_code": "import torch\nx=torch.add(torch.tensor(1),torch.tensor(2))\nassert x.item()==3\n"},
    ]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        events = root / "events.jsonl"
        events.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")
        manifest = run(events, root / "out", "B3", None)
        summary_rows = list(csv.DictReader((root / "out" / "ablation_summary.csv").open(encoding="utf-8")))
        promoted = {(row["condition"], row["stage"]): row for row in summary_rows}
        assert promoted[("full", "promoted_counterfactual")]["n_pass"] == "1"
        assert promoted[("full", "promoted_counterfactual")]["n_pending"] == "1"
        assert promoted[("no_ast", "promoted_counterfactual")]["n_pass"] == "2"
        assert promoted[("no_vn", "promoted_counterfactual")]["n_pass"] == "2"
        assert promoted[("no_atlas", "promoted_counterfactual")]["n_pass"] == "2"
        assert manifest["same_corpus_verified"] is True
        assert len(set(manifest["condition_corpus_sha256"].values())) == 1
        assert manifest["decoding_seed_evidence_complete"] is True
        assert manifest["fine_tuning_ablation"]["regeneration_required"] is True
        for name in ("ablation_decisions.jsonl", "ablation_summary.csv", "ablation_table.tex", "ablation_manifest.json", "fine_tuning_pairs.csv"):
            assert (root / "out" / name).is_file()

        # Tri-state semantics: pending propagates unless a prior gate has failed.
        assert tri_and(True, None) is None
        assert tri_and(False, None) is False
        assert tri_not(None) is None
        assert status_known("pending") is None

        # no_ast may remove a quality rule, never the immutable safety screen.
        unsafe = {**common, "baseline": "B3", "task_id": "unsafe", "extracted_code": "import os\nimport torch\nx=torch.add(torch.tensor(1),torch.tensor(2))\nassert x.item()==3\n"}
        unsafe_decision = replay_one(unsafe, "no_ast", {}, False)
        assert unsafe_decision["static"]["safety_pass"] is False
        assert unsafe_decision["stages"]["ast_pass"] is False
        fake = inspect_code(
            "import torch\nx=torch.tensor([1.])\ntorch.testing.assert_close(x,x)\n",
            "torch.tensor",
        )
        assert fake.fake_assertion is True and fake.oracle_present is False

        def expect_value_error(mutated_rows: list[dict[str, Any]], expected: str) -> None:
            bad_events = root / "bad.jsonl"
            bad_events.write_text("".join(canonical_json(row) + "\n" for row in mutated_rows), encoding="utf-8")
            try:
                run(bad_events, root / "bad-out", "B3", None)
            except ValueError as exc:
                assert expected.lower() in str(exc).lower(), str(exc)
            else:
                raise AssertionError(f"Expected fail-closed ValueError containing {expected!r}")

        corrupted = dict(rows[0], raw_output_sha256="0" * 64)
        expect_value_error([corrupted], "SHA-256 mismatch")
        no_seed = dict(rows[0]); no_seed.pop("generation_seed")
        expect_value_error([no_seed], "true decoding seed")
        no_seed_evidence = dict(rows[0]); no_seed_evidence.pop("seed_backend")
        expect_value_error([no_seed_evidence], "sampler plumbing")
        two_runs = [dict(rows[0], run_signature="A"), dict(rows[1], run_signature="B")]
        expect_value_error(two_runs, "Multiple run signatures")
        expect_value_error([rows[0], rows[0]], "Duplicate event IDs")
        try:
            fine_tuning_pairs([rows[-1], rows[-1]])
        except ValueError as exc:
            assert "fine-tuning pair key" in str(exc)
        else:
            raise AssertionError("Duplicate B2/B3 pair members must fail closed")
    print("SELF_TEST_PASS: deterministic same-corpus replay, tri-state funnel, and B2/B3 separation")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, help="Benchmark/candidate JSONL event stream")
    parser.add_argument("--out", type=Path, help="Output directory")
    parser.add_argument("--baseline", default="B3", choices=("B3", "ALL"), help="Frozen replay corpus (default: tuned B3 only)")
    parser.add_argument("--atlas", type=Path, help="Optional frozen Atlas JSONL for exact fingerprint-to-cluster replay")
    parser.add_argument("--run-signature", help="Select one run when the append-only JSONL contains multiple run signatures")
    parser.add_argument(
        "--evidence-label", choices=EVIDENCE_LABELS, default="validation_only",
        help="Provenance label embedded in the manifest/table (default: validation_only)",
    )
    parser.add_argument("--self-test", action="store_true", help="Run deterministic built-in smoke test")
    args = parser.parse_args(argv)
    if not args.self_test and (args.events is None or args.out is None):
        parser.error("--events and --out are required unless --self-test is used")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    manifest = run(args.events, args.out, args.baseline, args.atlas, args.run_signature, args.evidence_label)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
