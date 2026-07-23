#!/usr/bin/env python3
"""Compact fail-closed verifier for the two-seed ablation checkpoint."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import replay_ablation as replay


HERE = Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parents[2]
DEFAULT_CHECKPOINT = HERE / "two_seed_checkpoint"
EXPECTED_CONDITIONS = {"full", "no_ast", "no_oracle", "no_vn", "no_atlas"}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected a JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(all(isinstance(row, dict) for row in rows), f"{path}: expected JSON object rows")
    return rows


def source_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def source_digest(path: Path, mode: str) -> str:
    if mode == "bytes":
        return sha256(path)
    if mode == "canonical_json_utf8":
        return replay.sha256_text(replay.canonical_json(load_json(path)))
    raise VerificationError(f"unsupported source hash mode: {mode!r}")


def verify(checkpoint: Path = DEFAULT_CHECKPOINT) -> dict[str, Any]:
    checkpoint = checkpoint.resolve()
    manifest = load_json(checkpoint / "ablation_manifest.json")
    require(manifest.get("schema_version") == "trdgl_two_seed_ablation_checkpoint_v1", "wrong schema version")
    require(manifest.get("evidence_label") == "diagnostic_checkpoint", "wrong evidence label")
    require(manifest.get("collector_sha256") == sha256(HERE / "collect_two_seed_checkpoint.py"),
            "collector hash mismatch")
    require(manifest.get("replay_script_sha256") == sha256(HERE / "replay_ablation.py"),
            "replay script hash mismatch")

    for key, raw in manifest["source"].items():
        if not key.endswith("_path"):
            continue
        hash_key = key[:-5] + "_sha256"
        mode_key = key[:-5] + "_hash_mode"
        path = source_path(raw)
        require(path.is_file(), f"source file missing: {path}")
        require(manifest["source"].get(hash_key) == source_digest(path, manifest["source"].get(mode_key)),
                f"source hash mismatch: {key}")

    for name, expected in manifest.get("artifact_sha256", {}).items():
        path = checkpoint / name
        require(path.is_file(), f"checkpoint artifact missing: {name}")
        require(sha256(path) == expected, f"checkpoint artifact hash mismatch: {name}")

    coverage = manifest["coverage"]
    require(coverage == {
        "observed_seeds": [3407, 7711],
        "required_seeds": [3407, 7711, 12011, 19001, 27103],
        "complete_seed_shards": 2,
        "required_seed_shards": 5,
        "all_baseline_events": 960,
        "planned_all_baseline_events": 2400,
        "b3_events_replayed": 240,
        "planned_b3_events": 600,
    }, "coverage boundary changed")
    require(manifest.get("configuration_equivalence_verified") is True, "configuration equivalence is not verified")
    require(len(manifest.get("shards", [])) == 2, "shard audit count is not two")
    require({row["generation_seed"] for row in manifest["shards"]} == {3407, 7711}, "shard seeds changed")
    for shard in manifest["shards"]:
        require(shard.get("events") == 480, "a shard is not complete")
        require(shard.get("baseline_counts") == {"B0": 120, "B1": 120, "B2": 120, "B3": 120},
                "a shard baseline count changed")
        require(shard.get("same_corpus_verified") is True, "a shard lost same-corpus verification")
        require(shard.get("complete_b2_b3_pairs") == 120, "a shard lost B2/B3 pairs")
        require(shard.get("prompt_hash_mismatches") == 0, "a shard contains a prompt mismatch")

    decisions = load_jsonl(checkpoint / "ablation_decisions.jsonl")
    require(len(decisions) == 1200, "decision ledger is not 5 x 240 rows")
    require(Counter(row.get("condition") for row in decisions) == Counter({name: 240 for name in EXPECTED_CONDITIONS}),
            "per-condition decision counts changed")
    require(len({(row["condition"], row["event_id"]) for row in decisions}) == 1200,
            "decision keys are not unique")
    require(all(row.get("evidence_label") == "diagnostic_checkpoint" for row in decisions),
            "decision evidence labels changed")
    require(all("raw_output" not in row and "extracted_code" not in row for row in decisions),
            "decision ledger unexpectedly embeds generated code")
    replay.validate_same_corpus(decisions)
    hashes = replay.condition_corpus_hashes(decisions)
    require(hashes == manifest["condition_corpus_sha256"], "condition corpus hashes changed")
    require(set(hashes.values()) == {manifest["corpus_sha256"]}, "conditions do not share one corpus hash")

    with (checkpoint / "ablation_summary.csv").open(encoding="utf-8", newline="") as handle:
        summary = list(csv.DictReader(handle))
    require(len(summary) == len(replay.CONDITIONS) * len(replay.STAGES), "summary row count changed")
    indexed = {(row["condition"], row["stage"]): row for row in summary}

    def counts(condition: str, stage: str) -> tuple[int, int, int]:
        row = indexed[(condition, stage)]
        return int(row["n_pass"]), int(row["n_fail"]), int(row["n_pending"])

    require(counts("full", "raw") == (240, 0, 0), "full raw count changed")
    require(counts("full", "parseable") == (5, 235, 0), "full parseable count changed")
    require(counts("full", "ast_pass") == (5, 235, 0), "full AST count changed")
    require(counts("full", "runnable") == (4, 236, 0), "full runnable count changed")
    require(counts("full", "target_valid") == (1, 239, 0), "full target-valid count changed")
    require(counts("full", "oracle_bearing") == (0, 240, 0), "full oracle count changed")
    require(counts("no_ast", "ast_pass") == (5, 235, 0), "no-AST count changed")
    require(counts("no_oracle", "oracle_bearing") == (1, 239, 0), "no-oracle pass-through changed")
    require(counts("no_oracle", "reproducible") == (0, 239, 1), "no-oracle downstream pending count changed")
    require(counts("no_vn", "reproducible") == (0, 240, 0), "no-Vn boundary changed")
    require(counts("no_atlas", "non_duplicate") == (0, 240, 0), "no-Atlas boundary changed")

    effects = manifest["component_effects"]
    require(effects["ast_quality_policy"]["observed_pass_delta"] == 0, "AST delta changed")
    require(effects["ast_quality_policy"]["conclusive_effectiveness_estimate"] is None,
            "AST checkpoint was upgraded to a conclusive estimate")
    require(effects["oracle_gate"]["observed_pass_delta"] == 1, "oracle bypass delta changed")
    require(effects["oracle_gate"]["confirmed_bug_yield_effect"] is None,
            "oracle bypass was mislabeled as confirmed yield")
    require(effects["verified_novelty_gate"]["eligible_oracle_bearing_programs"] == 0,
            "Vn unexpectedly has eligible B3 input")
    require(effects["verified_novelty_gate"]["effectiveness_estimate"] is None,
            "Vn unavailable effect was converted to zero/value")
    require(effects["atlas_duplicate_gate"]["eligible_reproduced_programs"] == 0,
            "Atlas unexpectedly has eligible B3 input")
    require(effects["atlas_duplicate_gate"]["effectiveness_estimate"] is None,
            "Atlas unavailable effect was converted to zero/value")
    require(effects["atlas_duplicate_gate"]["raw_atlas_available"] is False,
            "raw Atlas availability changed")

    with (checkpoint / "fine_tuning_pairs.csv").open(encoding="utf-8", newline="") as handle:
        pairs = list(csv.DictReader(handle))
    require(len(pairs) == 240, "fine-tuning pair count is not 240")
    require(all(row["has_b2"] == "True" and row["has_b3"] == "True" and row["same_prompt_hash"] == "True"
                for row in pairs), "fine-tuning pairs are incomplete or prompt-mismatched")

    with (checkpoint / "fine_tuning_contrast.csv").open(encoding="utf-8", newline="") as handle:
        contrast = {row["stage"]: row for row in csv.DictReader(handle)}
    expected = {
        "parseable": (140, 5, 140, 5),
        "ast_pass": (140, 5, 139, 5),
        "runnable": (134, 4, 133, 4),
        "target_valid": (95, 1, 94, 1),
        "oracle_bearing": (88, 0, 87, 0),
    }
    for stage, values in expected.items():
        row = contrast[stage]
        observed = tuple(int(row[key]) for key in (
            "b2_pass", "b3_pass", "b2_cumulative_ablation_policy_pass", "b3_cumulative_ablation_policy_pass"
        ))
        require(observed == values, f"paired contrast changed at {stage}")
    audit = manifest["fine_tuning_contrast"]["pair_audit"]
    require(audit.get("complete_pairs") == 240 and audit.get("prompt_hash_mismatches") == 0,
            "manifest pairing audit changed")
    require(manifest["fine_tuning_contrast"].get("improvement_claim_supported") is False,
            "checkpoint was mislabeled as a tuning improvement")

    require("Diagnostic campaign checkpoint" in (checkpoint / "ablation_table.tex").read_text(encoding="utf-8"),
            "LaTeX table lost its diagnostic caption")
    require(manifest.get("full_campaign_complete") is False, "checkpoint marked full-campaign complete")
    require(manifest.get("ready_for_paper_result") is False, "checkpoint marked paper-ready")

    return {
        "result": "pass",
        "seeds": 2,
        "b3_events": 240,
        "decisions": 1200,
        "ast_delta": 0,
        "oracle_bypass_delta": 1,
        "vn_effect": None,
        "atlas_effect": None,
        "paired_prompts": 240,
        "paper_ready": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(verify(args.checkpoint), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
