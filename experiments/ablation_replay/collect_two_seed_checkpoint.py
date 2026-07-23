#!/usr/bin/env python3
"""Build a fail-closed two-seed ablation checkpoint from immutable shards.

The collector never generates or executes a model. Each complete seed shard is
validated and replayed separately so distinct run signatures are not mixed;
only the resulting decisions and counts are aggregated afterward.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import replay_ablation as replay


HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parents[1]
WORKSPACE_ROOT = HERE.parents[2]
DEFAULT_INDEX = HERE.parent / "benchmark_results" / "two_seed_checkpoint" / "campaign_shards.json"
DEFAULT_SUMMARY = HERE.parent / "benchmark_results" / "two_seed_checkpoint" / "summary.json"
DEFAULT_ATLAS_BLOCKER = HERE.parent / "atlas_intervention" / "two_seed_checkpoint" / "atlas_blocker_manifest.json"
DEFAULT_OUTPUT = HERE / "two_seed_checkpoint"
EVIDENCE_LABEL = "diagnostic_checkpoint"
EARLY_STAGES = ("parseable", "ast_pass", "runnable", "target_valid", "oracle_bearing")


class CollectionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectionError(message)


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


def canonical_json_file_sha256(path: Path) -> str:
    return replay.sha256_text(replay.canonical_json(load_json(path)))


def canonical_event_rows(rows: Iterable[dict[str, Any]]) -> list[str]:
    return sorted(replay.canonical_json({key: value for key, value in row.items() if key != "_source_line"}) for row in rows)


def portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def resolve_path(raw: str, relative_to: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve()
        require(resolved.is_file(), f"source file does not exist: {resolved}")
        return resolved
    candidates = (
        (relative_to / path).resolve(),
        (WORKSPACE_ROOT / path).resolve(),
        (PAPER_ROOT / path).resolve(),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CollectionError(f"cannot resolve source path {raw!r}")


def write_json(path: Path, value: Any) -> None:
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    payload = "".join(replay.canonical_json(row) + "\n" for row in rows)
    path.write_bytes(payload.encode("utf-8"))


def write_csv_lf(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_bytes(b"")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def configuration_fingerprint(manifest: dict[str, Any]) -> str:
    stable = {key: value for key, value in manifest.items() if key not in {"created_utc", "event_log", "run_signature"}}
    return replay.sha256_text(replay.canonical_json(stable))


def stage_index(summary_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["condition"], row["stage"]): row for row in summary_rows}


def observed_early_counts(rows: list[dict[str, Any]], baseline: str) -> dict[str, int]:
    decisions = [replay.replay_one(row, "full", {}, False) for row in rows if row.get("baseline") == baseline]
    return {
        stage: sum(decision["stages"][stage] is True for decision in decisions)
        for stage in EARLY_STAGES
    }


def paired_contrast_rows(benchmark_summary: dict[str, Any], combined_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paired = benchmark_summary["fairness"]["paired_outcomes"]
    require(paired.get("eligible_pair_count") == 240, "benchmark summary does not contain 240 eligible B2/B3 pairs")
    observed = {baseline: observed_early_counts(combined_rows, baseline) for baseline in ("B2", "B3")}
    coverage = benchmark_summary["coverage"]["by_baseline"]
    output: list[dict[str, Any]] = []
    for stage in EARLY_STAGES:
        metric = paired["metrics"][stage]
        b2_pass = int(metric["both_pass"]) + int(metric["b2_only_pass"])
        b3_pass = int(metric["both_pass"]) + int(metric["b3_only_pass"])
        require(b2_pass == coverage["B2"][f"{stage}_count"],
                f"B2 {stage} paired count disagrees with benchmark coverage")
        require(b3_pass == coverage["B3"][f"{stage}_count"],
                f"B3 {stage} paired count disagrees with benchmark coverage")
        require(b3_pass == observed["B3"][stage],
                f"B3 {stage} disagrees between benchmark and ablation replay")
        require(observed["B2"][stage] <= b2_pass,
                f"B2 cumulative ablation count exceeds the independently observed benchmark count at {stage}")
        output.append({
            "stage": stage,
            "eligible_pairs": metric["eligible_pairs"],
            "b2_pass": b2_pass,
            "b3_pass": b3_pass,
            "b2_cumulative_ablation_policy_pass": observed["B2"][stage],
            "b3_cumulative_ablation_policy_pass": observed["B3"][stage],
            "b2_pass_rate": metric["b2_pass_rate"],
            "b3_pass_rate": metric["b3_pass_rate"],
            "b3_minus_b2_paired_rate": metric["b3_minus_b2_paired_rate"],
            "both_pass": metric["both_pass"],
            "b2_only_pass": metric["b2_only_pass"],
            "b3_only_pass": metric["b3_only_pass"],
            "both_fail": metric["both_fail"],
            "mcnemar_exact_two_sided_p": metric["mcnemar_exact_two_sided_p"],
            "metric_semantics": "paired benchmark-harness outcome; cumulative ablation-policy counts are separate audit columns",
            "evidence_label": EVIDENCE_LABEL,
        })
    return output


def component_effects(summary_rows: list[dict[str, Any]], atlas_blocker: dict[str, Any]) -> dict[str, Any]:
    indexed = stage_index(summary_rows)

    def count(condition: str, stage: str, field: str = "n_pass") -> int:
        return int(indexed[(condition, stage)][field])

    return {
        "ast_quality_policy": {
            "comparison": "no_ast versus full on the same B3 programs",
            "eligible_parseable_programs": count("full", "parseable"),
            "full_ast_pass": count("full", "ast_pass"),
            "no_ast_pass": count("no_ast", "ast_pass"),
            "observed_pass_delta": count("no_ast", "ast_pass") - count("full", "ast_pass"),
            "conclusive_effectiveness_estimate": None,
            "reason": "Only five B3 programs are parseable in this 2/5-seed checkpoint; syntax and immutable safety remain enabled in both arms.",
        },
        "oracle_gate": {
            "comparison": "no_oracle versus full on the same B3 programs",
            "eligible_target_valid_programs": count("full", "target_valid"),
            "full_oracle_gate_pass": count("full", "oracle_bearing"),
            "no_oracle_gate_pass": count("no_oracle", "oracle_bearing"),
            "observed_pass_delta": count("no_oracle", "oracle_bearing") - count("full", "oracle_bearing"),
            "no_oracle_reproducible_pending": count("no_oracle", "reproducible", "n_pending"),
            "confirmed_bug_yield_effect": None,
            "reason": "The bypass admits one target-valid program counterfactually, but its anomaly/reproduction evidence is pending.",
        },
        "verified_novelty_gate": {
            "comparison": "no_vn versus full on the same B3 programs",
            "eligible_oracle_bearing_programs": count("full", "oracle_bearing"),
            "full_reproducible_pass": count("full", "reproducible"),
            "no_vn_reproducible_pass": count("no_vn", "reproducible"),
            "effectiveness_estimate": None,
            "reason": "No B3 program reaches the oracle-bearing input boundary, so a zero delta is not an estimate of Vn effectiveness.",
        },
        "atlas_duplicate_gate": {
            "comparison": "no_atlas versus full on the same B3 programs",
            "eligible_reproduced_programs": count("full", "reproducible"),
            "full_non_duplicate_pass": count("full", "non_duplicate"),
            "no_atlas_non_duplicate_pass": count("no_atlas", "non_duplicate"),
            "effectiveness_estimate": None,
            "raw_atlas_available": False,
            "reason": "No reproduced B3 input reaches duplicate triage, and the independently verifiable raw Atlas source is absent.",
            "atlas_blocker_ready_for_paper": atlas_blocker.get("ready_for_paper_result"),
        },
    }


def write_checkpoint_markdown(path: Path, manifest: dict[str, Any]) -> None:
    effects = manifest["component_effects"]
    contrast = {row["stage"]: row for row in manifest["fine_tuning_contrast"]["metrics"]}
    lines = [
        "# Two-seed ablation diagnostic checkpoint",
        "",
        "This bundle replays immutable B3 programs from complete seed shards 3407 and 7711. "
        "It covers 240/600 planned B3 programs (2/5 seeds) and is not a final paper result.",
        "",
        "## Measured boundary",
        "",
        f"- Full B3 funnel: 240 raw -> {effects['ast_quality_policy']['eligible_parseable_programs']} parseable/AST-pass "
        f"-> {effects['oracle_gate']['eligible_target_valid_programs']} target-valid -> "
        f"{effects['verified_novelty_gate']['eligible_oracle_bearing_programs']} oracle-bearing.",
        f"- Removing the ablatable AST quality policy changes AST-pass by "
        f"{effects['ast_quality_policy']['observed_pass_delta']}; this is descriptive, not conclusive.",
        f"- Removing the oracle gate admits {effects['oracle_gate']['observed_pass_delta']} additional program, "
        f"but {effects['oracle_gate']['no_oracle_reproducible_pending']} downstream decision remains pending.",
        "- Vn and Atlas effects are unavailable, not zero: neither gate has an eligible B3 input at this checkpoint.",
        "",
        "## Paired base-versus-tuned diagnostic",
        "",
        f"All 240 B2/B3 pairs share the same prompt hash. B2 versus B3 target-valid counts are "
        f"{contrast['target_valid']['b2_pass']}/240 versus {contrast['target_valid']['b3_pass']}/240; "
        f"oracle-bearing counts are {contrast['oracle_bearing']['b2_pass']}/240 versus "
        f"{contrast['oracle_bearing']['b3_pass']}/240. This checkpoint does not support a tuning-improvement claim.",
        "",
        "## Claim boundary",
        "",
        manifest["claim_boundary"],
        "",
    ]
    path.write_bytes("\n".join(lines).encode("utf-8"))


def collect(index_path: Path, summary_path: Path, atlas_blocker_path: Path, output_dir: Path) -> dict[str, Any]:
    index_path = index_path.resolve()
    summary_path = summary_path.resolve()
    atlas_blocker_path = atlas_blocker_path.resolve()
    index = load_json(index_path)
    benchmark_summary = load_json(summary_path)
    atlas_blocker = load_json(atlas_blocker_path)

    require(index.get("schema_version") == "trdgl_campaign_shard_index_v1", "unexpected campaign shard schema")
    require(benchmark_summary.get("full_benchmark_complete") is False, "source unexpectedly claims a full campaign")
    require(benchmark_summary.get("ready_for_paper_result") is False, "source unexpectedly claims paper readiness")
    require(benchmark_summary["fairness"].get("configuration_equivalence_verified") is True,
            "benchmark summary did not verify configuration equivalence")
    require(benchmark_summary["fairness"].get("harness_equivalence_verified") is True,
            "benchmark summary did not verify harness equivalence")
    require(atlas_blocker.get("evidence_label") == EVIDENCE_LABEL, "Atlas blocker has the wrong evidence label")
    require(atlas_blocker.get("ready_for_paper_result") is False, "Atlas blocker is unexpectedly paper-ready")

    combined_path = resolve_path(benchmark_summary["source"]["events_path"], summary_path.parent)
    require(sha256(combined_path) == benchmark_summary["source"]["events_sha256"], "combined event hash mismatch")
    combined_rows = replay.read_jsonl(combined_path)
    require(len(combined_rows) == benchmark_summary["coverage"]["observed_event_count"] == 960,
            "combined event count is not 960")
    require(benchmark_summary["benchmark"]["expected_event_count"] == 2400, "planned campaign size is not 2400")

    required_seeds = [int(seed) for seed in benchmark_summary["benchmark"]["generation_seeds"]]
    shard_entries = index.get("shards", [])
    require(isinstance(shard_entries, list) and len(shard_entries) == 2, "checkpoint must contain exactly two shards")
    observed_seeds = [int(entry["generation_seed"]) for entry in shard_entries]
    require(len(set(observed_seeds)) == 2 and set(observed_seeds).issubset(required_seeds), "invalid shard seed set")

    all_decisions: list[dict[str, Any]] = []
    all_shard_rows: list[dict[str, Any]] = []
    shard_audit: list[dict[str, Any]] = []
    config_hashes: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="trdgl-ablation-") as temporary:
        temporary_root = Path(temporary)
        for entry in sorted(shard_entries, key=lambda value: int(value["generation_seed"])):
            seed = int(entry["generation_seed"])
            events_path = resolve_path(entry["events_path"], index_path.parent)
            run_manifest_path = resolve_path(entry["run_manifest_path"], index_path.parent)
            run_manifest = load_json(run_manifest_path)
            signature = str(entry["run_signature"])
            require(run_manifest.get("run_signature") == signature, f"seed {seed}: run signature mismatch")
            require(int(run_manifest.get("selected_task_count", 0)) == 120, f"seed {seed}: task count is not 120")

            rows = replay.read_jsonl(events_path)
            require(len(rows) == 480, f"seed {seed}: event count is not 480")
            require({int(replay.first(row, "generation_seed", "seed", "decoding_seed")) for row in rows} == {seed},
                    f"seed {seed}: event ledger contains another generation seed")
            require({str(row.get("run_signature")) for row in rows} == {signature},
                    f"seed {seed}: event ledger contains another run signature")
            counts = Counter(str(row.get("baseline")) for row in rows)
            require(counts == Counter({"B0": 120, "B1": 120, "B2": 120, "B3": 120}),
                    f"seed {seed}: baseline counts are not 120 each")

            shard_out = temporary_root / f"seed{seed}"
            replay_manifest = replay.run(
                events_path, shard_out, "B3", None,
                run_signature=signature, evidence_label=EVIDENCE_LABEL,
            )
            require(replay_manifest["raw_event_count"] == 120 and replay_manifest["same_corpus_verified"] is True,
                    f"seed {seed}: replay did not verify 120 B3 events")
            decisions = replay.read_jsonl(shard_out / "ablation_decisions.jsonl")
            require(len(decisions) == len(replay.CONDITIONS) * 120, f"seed {seed}: decision count mismatch")
            for decision in decisions:
                decision.pop("_source_line", None)
            all_decisions.extend(decisions)
            all_shard_rows.extend(rows)

            config_hash = configuration_fingerprint(run_manifest)
            config_hashes.add(config_hash)
            shard_audit.append({
                "generation_seed": seed,
                "run_signature": signature,
                "events_path": portable_path(events_path),
                "events_sha256": sha256(events_path),
                "events": len(rows),
                "baseline_counts": dict(sorted(counts.items())),
                "run_manifest_path": portable_path(run_manifest_path),
                "run_manifest_sha256": sha256(run_manifest_path),
                "configuration_sha256": config_hash,
                "b3_corpus_sha256": replay_manifest["corpus_sha256"],
                "same_corpus_verified": True,
                "complete_b2_b3_pairs": replay_manifest["fine_tuning_ablation"]["complete_pairs"],
                "prompt_hash_mismatches": replay_manifest["fine_tuning_ablation"]["prompt_hash_mismatches"],
            })

    require(len(config_hashes) == 1, "seed run manifests are not configuration-equivalent")
    require(canonical_event_rows(all_shard_rows) == canonical_event_rows(combined_rows),
            "combined event ledger is not the exact union of indexed shards")
    require(len({(row["condition"], row["event_id"]) for row in all_decisions}) == len(all_decisions),
            "aggregated replay decisions are not unique")

    replay.validate_same_corpus(all_decisions)
    condition_hashes = replay.condition_corpus_hashes(all_decisions)
    selected_b3 = [row for row in combined_rows if row.get("baseline") == "B3"]
    require(len(selected_b3) == 240, "combined B3 corpus is not 240 events")
    corpus_hash = replay.corpus_hash(selected_b3)
    require(set(condition_hashes.values()) == {corpus_hash}, "aggregate conditions do not replay the same B3 corpus")

    condition_order = {name: index for index, name in enumerate(replay.CONDITIONS)}
    all_decisions.sort(key=lambda row: (condition_order[row["condition"]], int(row["generation_seed"]), row["event_id"]))
    summary_rows = replay.summarize(all_decisions)
    pairs, pair_report = replay.fine_tuning_pairs(combined_rows)
    require(pair_report == {
        "method": "paired B2 base+full-prompt versus B3 tuned+same-full-prompt",
        "regeneration_required": True,
        "reason": "Fine-tuning changes generated programs; it is not a downstream gate and cannot be replayed from frozen B3 outputs.",
        "pair_keys_seen": 240,
        "complete_pairs": 240,
        "incomplete_pairs": 0,
        "prompt_hash_mismatches": 0,
        "complete_same_prompt_pairs": 240,
        "fair_comparison_ready": True,
    }, "B2/B3 pairing audit mismatch")
    for rows in (all_decisions, summary_rows, pairs):
        for row in rows:
            row["evidence_label"] = EVIDENCE_LABEL

    contrast_rows = paired_contrast_rows(benchmark_summary, combined_rows)
    effects = component_effects(summary_rows, atlas_blocker)

    output_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = output_dir / "ablation_decisions.jsonl"
    summary_csv_path = output_dir / "ablation_summary.csv"
    table_path = output_dir / "ablation_table.tex"
    pairs_path = output_dir / "fine_tuning_pairs.csv"
    contrast_path = output_dir / "fine_tuning_contrast.csv"
    checkpoint_path = output_dir / "checkpoint.md"
    manifest_path = output_dir / "ablation_manifest.json"

    write_jsonl(decisions_path, all_decisions)
    write_csv_lf(summary_csv_path, summary_rows)
    replay.write_latex(table_path, summary_rows, EVIDENCE_LABEL)
    table_path.write_bytes(table_path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8"))
    write_csv_lf(pairs_path, pairs)
    write_csv_lf(contrast_path, contrast_rows)

    manifest: dict[str, Any] = {
        "schema_version": "trdgl_two_seed_ablation_checkpoint_v1",
        "evidence_label": EVIDENCE_LABEL,
        "policy_version": replay.POLICY_VERSION,
        "collector_sha256": sha256(Path(__file__)),
        "replay_script_sha256": sha256(HERE / "replay_ablation.py"),
        "source": {
            "campaign_index_path": portable_path(index_path),
            "campaign_index_sha256": canonical_json_file_sha256(index_path),
            "campaign_index_hash_mode": "canonical_json_utf8",
            "benchmark_summary_path": portable_path(summary_path),
            "benchmark_summary_sha256": canonical_json_file_sha256(summary_path),
            "benchmark_summary_hash_mode": "canonical_json_utf8",
            "combined_events_path": portable_path(combined_path),
            "combined_events_sha256": sha256(combined_path),
            "combined_events_hash_mode": "bytes",
            "atlas_blocker_path": portable_path(atlas_blocker_path),
            "atlas_blocker_sha256": canonical_json_file_sha256(atlas_blocker_path),
            "atlas_blocker_hash_mode": "canonical_json_utf8",
        },
        "coverage": {
            "observed_seeds": sorted(observed_seeds),
            "required_seeds": required_seeds,
            "complete_seed_shards": 2,
            "required_seed_shards": 5,
            "all_baseline_events": 960,
            "planned_all_baseline_events": 2400,
            "b3_events_replayed": 240,
            "planned_b3_events": 600,
        },
        "shards": shard_audit,
        "configuration_equivalence_verified": True,
        "configuration_sha256": next(iter(config_hashes)),
        "baseline_replayed": "B3",
        "conditions": list(replay.CONDITIONS),
        "condition_event_counts": {
            condition: sum(row["condition"] == condition for row in all_decisions)
            for condition in replay.CONDITIONS
        },
        "corpus_sha256": corpus_hash,
        "condition_corpus_sha256": condition_hashes,
        "same_corpus_verified": True,
        "component_effects": effects,
        "fine_tuning_contrast": {
            "design": "paired B2 base versus B3 tuned generations with identical full-prompt hashes and the same benchmark harness",
            "pair_audit": pair_report,
            "metrics": contrast_rows,
            "improvement_claim_supported": False,
            "reason": "At this two-seed checkpoint B3 is worse than B2 on every early validity metric; the five-seed campaign remains incomplete.",
        },
        "full_campaign_complete": False,
        "ready_for_paper_result": False,
        "blockers": [
            "three_required_seed_shards_missing",
            "b3_oracle_bearing_count_zero",
            "vn_has_no_eligible_b3_input",
            "atlas_has_no_eligible_b3_input",
            "raw_atlas_dataset_absent",
            "post_oracle_candidate_triage_incomplete",
        ],
        "claim_boundary": "Complete two-seed ablation diagnostic checkpoint only. It reports observed gate pass-through counts and unavailable effects; it is not the planned five-seed ablation and not evidence of confirmed bug yield.",
    }
    write_checkpoint_markdown(checkpoint_path, manifest)
    artifact_paths = (decisions_path, summary_csv_path, table_path, pairs_path, contrast_path, checkpoint_path)
    manifest["artifact_sha256"] = {path.name: sha256(path) for path in artifact_paths}
    write_json(manifest_path, manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--benchmark-summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--atlas-blocker", type=Path, default=DEFAULT_ATLAS_BLOCKER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = collect(args.campaign_index, args.benchmark_summary, args.atlas_blocker, args.out)
    effects = manifest["component_effects"]
    print(json.dumps({
        "result": "pass",
        "seeds": len(manifest["coverage"]["observed_seeds"]),
        "b3_events": manifest["coverage"]["b3_events_replayed"],
        "ast_delta": effects["ast_quality_policy"]["observed_pass_delta"],
        "oracle_bypass_delta": effects["oracle_gate"]["observed_pass_delta"],
        "vn_effect": effects["verified_novelty_gate"]["effectiveness_estimate"],
        "atlas_effect": effects["atlas_duplicate_gate"]["effectiveness_estimate"],
        "paper_ready": manifest["ready_for_paper_result"],
    }, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
