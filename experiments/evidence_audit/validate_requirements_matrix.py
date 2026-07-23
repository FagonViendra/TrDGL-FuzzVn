"""Fail-closed validation for the experimental evidence-gap matrix."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
MATRIX = HERE / "requirements_matrix.json"
CAMPAIGN_SUMMARY = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/benchmark_results/two_seed_checkpoint/summary.json"
CHECKPOINT_PROVENANCE = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/benchmark_results/validation_output/seed3407.live.provenance.json"
GENERATION_ERROR_MANIFEST = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/generation_error_analysis/two_seed_checkpoint/analysis_manifest.json"
ABLATION_MANIFEST = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/ablation_replay/two_seed_checkpoint/ablation_manifest.json"
VN_FUNNEL = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/vn_funnel/two_seed_checkpoint/funnel_report.json"
NUMERICAL_MANIFEST = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/numerical_oracle/five_seed_local_checkpoint/diagnostic_manifest.json"
DIAGNOSTIC_CANDIDATES = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/vn_funnel/two_seed_checkpoint/candidate_ledger.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_semantic_sources(matrix: dict) -> dict:
    """Cross-check mutable audit prose against the machine-readable campaign."""
    campaign = json.loads(CAMPAIGN_SUMMARY.read_text(encoding="utf-8"))
    provenance = json.loads(CHECKPOINT_PROVENANCE.read_text(encoding="utf-8"))
    generation = json.loads(GENERATION_ERROR_MANIFEST.read_text(encoding="utf-8"))
    ablation = json.loads(ABLATION_MANIFEST.read_text(encoding="utf-8"))
    vn_funnel = json.loads(VN_FUNNEL.read_text(encoding="utf-8"))
    numerical = json.loads(NUMERICAL_MANIFEST.read_text(encoding="utf-8"))
    facts = matrix["observed_artifact_facts"]
    observed = campaign["coverage"]["observed_event_count"]
    expected = campaign["benchmark"]["expected_event_count"]
    baseline_counts = {
        baseline: entry["observed_events"]
        for baseline, entry in campaign["coverage"]["by_baseline"].items()
    }
    assert facts["planned_events"] == expected
    assert facts["immutable_campaign_checkpoint_events"] == observed
    assert facts["immutable_campaign_checkpoint_expected_events"] == expected
    assert facts["latest_validated_mutable_checkpoint_events"] == observed
    assert facts["latest_validated_mutable_checkpoint_baselines"] == baseline_counts
    assert facts["complete_campaign_seed_shards"] == 2
    assert facts["complete_campaign_seed_values"] == [3407, 7711]
    assert facts["complete_b2_b3_pairs"] == campaign["fairness"]["complete_b2_b3_pairs"] == 240
    assert facts["prompt_hash_mismatch_count"] == campaign["fairness"]["prompt_hash_mismatch_count"] == 0
    assert campaign["fairness"]["configuration_equivalence_verified"]
    assert campaign["fairness"]["harness_equivalence_verified"]
    assert provenance["persisted_raw_event_count"] == 480
    assert provenance["paper_evidence_event_count"] == 480
    transcript = provenance["executed_notebook_transcript"]["observed_events"]
    assert facts["executed_notebook_transcript_events"] == transcript
    assert facts["transcript_events_without_persisted_jsonl"] == transcript - provenance["persisted_raw_event_count"]
    assert provenance["transcript_matches_persisted_raw_stream"]
    assert not provenance["blockers"]
    signatures = campaign["source"]["all_run_signatures"]
    assert len(signatures) == len(set(signatures)) == 2
    for seed in ("3407", "7711"):
        assert campaign["coverage"]["by_seed"][seed]["observed_events"] == 480
        assert campaign["coverage"]["by_seed"][seed]["complete"]
    unfinished_seeds = [
        seed
        for seed, entry in campaign["coverage"]["by_seed"].items()
        if not entry["complete"]
    ]
    assert sorted(unfinished_seeds) == ["12011", "19001", "27103"]
    assert not campaign["ready_for_paper_result"]
    assert set(campaign["blockers"]) == {
        "expected_events_missing",
        "b2_b3_pairs_incomplete",
        "campaign_seed_shards_missing",
    }

    integrity = generation["input_integrity"]
    assert sum(entry["records"] for entry in integrity) == facts["generation_error_checkpoint_records"] == 960
    assert {entry["generation_seeds"][0] for entry in integrity} == {"3407", "7711"}
    assert facts["generation_error_checkpoint_baselines"] == baseline_counts

    assert ablation["evidence_label"] == "diagnostic_checkpoint"
    assert ablation["coverage"]["b3_events_replayed"] == facts["ablation_diagnostic_raw_event_count"] == 240
    assert ablation["same_corpus_verified"]
    assert ablation["component_effects"]["ast_quality_policy"]["observed_pass_delta"] == 0
    assert ablation["component_effects"]["verified_novelty_gate"]["effectiveness_estimate"] is None
    assert ablation["component_effects"]["atlas_duplicate_gate"]["effectiveness_estimate"] is None
    assert not ablation["ready_for_paper_result"]

    stages = {row["stage"]: row for row in vn_funnel["funnel"]}
    assert vn_funnel["records"] == facts["vn_funnel_records"] == 960
    assert stages["oracle_bearing"]["pass"] == facts["vn_oracle_bearing_records"] == 89
    for stage in ("reproducible", "non_duplicate", "minimized", "stable_nightly", "promoted"):
        assert (stages[stage]["pass"], stages[stage]["fail"], stages[stage]["unknown"]) == (0, 0, 960)

    assert numerical["results"]["eager"]["measured_events"] == facts["numerical_eager_measured_events"] == 240
    assert numerical["results"]["compiled"]["unsupported_events"] == facts["numerical_compiled_unsupported_events"] == 240
    assert numerical["results"]["eager"]["clean_false_positives"] == facts["numerical_clean_false_positives"] == 0
    assert sum(numerical["results"]["status_counts"].values()) == facts["numerical_local_design_events"] == 480
    assert numerical["results"]["compiled"]["effect_estimate"] is None
    assert not numerical["certified_bound_present"]
    assert not numerical["ready_for_paper_result"]
    return {
        "campaign_observed_events": observed,
        "campaign_expected_events": expected,
        "baseline_counts": baseline_counts,
        "audited_shard_transcript_events": transcript,
        "persisted_evidence_ceiling": observed,
        "complete_seed_shards": 2,
        "paired_prompts": 240,
        "vn_oracle_bearing": 89,
        "ablation_b3_events": 240,
        "numerical_events": 480,
    }


def main() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    requirements = matrix["requirements"]
    semantic = validate_semantic_sources(matrix)

    ids = [row["id"] for row in requirements]
    assert ids == [f"R{i}" for i in range(1, 11)], ids
    statuses = Counter(row["status"] for row in requirements)
    expected_statuses = matrix["validation"]["status_count_recomputed"]
    assert dict(statuses) == expected_statuses, (statuses, expected_statuses)
    assert matrix["summary"]["done"] == statuses["done"]
    assert matrix["summary"]["partial"] == statuses["partial"]
    assert matrix["summary"]["missing"] == statuses["missing"]
    assert matrix["summary"]["strict_requirement_completion_rate"] == statuses["done"] / len(requirements)
    assert matrix["summary"]["requirements_with_any_inspectable_evidence_rate"] == (
        statuses["done"] + statuses["partial"]
    ) / len(requirements)

    evidence = [item for row in requirements for item in row["evidence"]]
    evidence_paths = sorted({item["path"] for item in evidence})
    missing = [path for path in evidence_paths if not (WORKSPACE / path).is_file()]
    assert not missing, missing
    assert len(evidence) == matrix["validation"]["evidence_entries"]
    assert len(evidence_paths) == matrix["validation"]["unique_evidence_paths"]

    for relative_path, expected_hash in matrix["audited_file_sha256"].items():
        actual_hash = sha256(WORKSPACE / relative_path)
        assert actual_hash == expected_hash, (relative_path, expected_hash, actual_hash)

    for relative_path in (
        "TrDGL-FuzzVn_paper/experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb",
        "TrDGL-FuzzVn_paper/experiments/benchmark_120/trdgl_fair_benchmark_120_output.ipynb",
    ):
        json.loads((WORKSPACE / relative_path).read_text(encoding="utf-8"))

    ledger = WORKSPACE / "TrDGL-FuzzVn_paper/experiments/vn_funnel/candidate_ledger.csv"
    artifact_paths: list[str] = []
    with ledger.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == matrix["validation"]["candidate_ledger_rows"]
    for row in rows:
        artifact_paths.extend(
            part.strip() for part in row["artifact_paths"].split(";") if part.strip()
        )
    missing_candidate_artifacts = [
        path for path in artifact_paths if not (WORKSPACE / path).is_file()
    ]
    assert not missing_candidate_artifacts, missing_candidate_artifacts
    assert len(artifact_paths) == matrix["validation"]["candidate_artifact_paths_listed"]

    diagnostic_rows = [
        json.loads(line) for line in DIAGNOSTIC_CANDIDATES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(diagnostic_rows) == matrix["validation"]["diagnostic_candidate_ledger_rows"] == 1
    diagnostic_artifacts = [
        path for row in diagnostic_rows for path in row.get("artifact_paths", [])
    ]
    assert len(diagnostic_artifacts) == matrix["validation"]["diagnostic_candidate_artifact_paths_listed"]
    assert all((WORKSPACE / path).is_file() for path in diagnostic_artifacts)

    report = {
        "result": "pass",
        "requirement_count": len(requirements),
        "status_count": dict(statuses),
        "evidence_entries": len(evidence),
        "unique_evidence_paths": len(evidence_paths),
        "audited_hashes": len(matrix["audited_file_sha256"]),
        "candidate_ledger_rows": len(rows),
        "candidate_artifact_paths_present": len(artifact_paths),
        "diagnostic_candidate_ledger_rows": len(diagnostic_rows),
        "diagnostic_candidate_artifact_paths_present": len(diagnostic_artifacts),
        "semantic_source_crosscheck": semantic,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
