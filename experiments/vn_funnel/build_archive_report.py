#!/usr/bin/env python3
"""Build an auditable report from the archived, partially logged evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import vn_funnel


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
FUNNEL_COLUMNS = vn_funnel.STAGES


def load_campaigns() -> list[dict[str, str]]:
    with (HERE / "archive_campaign_counts.csv").open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_ledger() -> list[dict]:
    return vn_funnel.load_jsonl(HERE / "candidate_ledger.jsonl")


def load_atlas() -> dict:
    return json.loads((HERE / "atlas_snapshot.json").read_text(encoding="utf-8"))


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build() -> dict:
    campaigns = load_campaigns()
    ledger = load_ledger()
    ledger_validation = vn_funnel.validate_ledger(HERE / "candidate_ledger.jsonl")
    artifact_files: list[dict] = []
    for row in ledger:
        for relative in row["artifact_paths"]:
            path = REPO_ROOT / relative
            if not path.is_file():
                raise FileNotFoundError(f"candidate evidence file is missing: {relative}")
            artifact_files.append({
                "candidate_id": row["candidate_id"],
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": hash_file(path),
            })
    atlas = load_atlas()
    if sum(atlas["framework_records"].values()) != atlas["records"]:
        raise ValueError("Atlas framework totals do not equal record total")
    if atlas["canonical_clusters"] > atlas["unique_issues"]:
        raise ValueError("Atlas clusters exceed unique issues")

    field_coverage = {
        stage: {
            "campaigns_logged": sum(bool(row.get("raw_count" if stage == "raw" else stage, "").strip()) for row in campaigns),
            "campaigns_missing": sum(not bool(row.get("raw_count" if stage == "raw" else stage, "").strip()) for row in campaigns),
        }
        for stage in FUNNEL_COLUMNS
    }
    duplicate_states = Counter(row["duplicate_checked"] for row in ledger)
    promotion_states = Counter(row["promoted"] for row in ledger)
    atlas_metrics = {
        "records": atlas["records"],
        "unique_issues": atlas["unique_issues"],
        "canonical_clusters": atlas["canonical_clusters"],
        "records_per_cluster": atlas["records"] / atlas["canonical_clusters"],
        "unique_issues_per_cluster": atlas["unique_issues"] / atlas["canonical_clusters"],
        "pytorch_record_share": atlas["framework_records"]["PyTorch"] / atlas["records"],
        "tensorflow_record_share": atlas["framework_records"]["TensorFlow"] / atlas["records"],
        "duplicate_candidates_detected": None,
        "atlas_guided_candidates": None,
        "causal_effect_available": False,
        "source_audit": atlas["source_audit"],
    }
    return {
        "report_version": "trdgl_archive_evidence_v1",
        "source_policy": "Missing means not logged, never zero. Campaign denominators are not pooled.",
        "campaigns": campaigns,
        "funnel_field_coverage": field_coverage,
        "candidate_ledger": {
            **ledger_validation,
            "duplicate_check_states": dict(sorted(duplicate_states.items())),
            "promotion_states": dict(sorted(promotion_states.items())),
            "fully_promoted_candidates": sum(row["promoted"] == "yes" for row in ledger),
            "artifact_files_audited": artifact_files,
        },
        "atlas": atlas_metrics,
        "claims_supported": [
            "Five candidate families have structured verification states.",
            "No candidate in the local ledger has a recorded completed Vn promotion.",
            "The paper reports an Atlas snapshot of 7,275 records, 5,868 unique issues, and 2,653 clusters.",
        ],
        "claims_not_supported": [
            "An aggregate archived raw-to-promoted conversion rate.",
            "The number of candidates de-duplicated by the Atlas.",
            "The number of generations planned or redirected by the Atlas.",
            "Independent recomputation of Atlas corpus counts from a raw local artifact.",
        ],
    }


def write_candidate_csv(rows: list[dict]) -> None:
    fields = [
        "candidate_id", "candidate_family", "framework", "apis", "scope",
        "reproduced", "duplicate_checked", "minimized", "stable_tested",
        "nightly_tested", "promoted", "evidence_level", "artifact_paths",
        "disposition", "evidence_source",
    ]
    with (HERE / "candidate_ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source in rows:
            row = {field: source.get(field, "") for field in fields}
            row["apis"] = "; ".join(source.get("apis", []))
            row["artifact_paths"] = "; ".join(source.get("artifact_paths", []))
            writer.writerow(row)


def tex_escape(value: object) -> str:
    text = str(value)
    for old, new in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")):
        text = text.replace(old, new)
    return text


def render_latex(report: dict, ledger_rows: list[dict]) -> str:
    status = {
        "yes": "Yes", "no": "No", "partial": "Partial",
        "pending": "Pending", "not_applicable": "N/A",
    }
    lines = [
        "% Generated by experiments/vn_funnel/build_archive_report.py.",
        "% Insert the first block in Section 4.5 (Vn Gate Effectiveness).",
        r"\begin{table}[H]",
        r"\centering\scriptsize",
        r"\caption{Coverage of ordered Vn-funnel fields in five archived campaigns. These are evidence-coverage counts, not stage conversion counts.}",
        r"\label{tab:vn_field_coverage}",
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"\textbf{Ordered stage} & \textbf{Campaigns logged} & \textbf{Campaigns missing} \\",
        r"\midrule",
    ]
    display_stage = {"ast_pass": "AST-pass", "target_valid": "target-valid", "oracle_bearing": "oracle-bearing", "non_duplicate": "non-duplicate", "stable_nightly": "stable/nightly"}
    for stage, counts in report["funnel_field_coverage"].items():
        label = display_stage.get(stage, stage)
        lines.append(f"{tex_escape(label)} & {counts['campaigns_logged']} & {counts['campaigns_missing']} \\\\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
        r"\noindent The archived campaigns cannot support a pooled raw-to-promoted conversion rate: no campaign logged every ordered field, and their units differ (APIs, prompts, candidates, and probes). Missing values are therefore reported as unavailable rather than zero. The machine-readable normalizer now enforces the order raw $\rightarrow$ parseable $\rightarrow$ AST-pass $\rightarrow$ runnable $\rightarrow$ target-valid $\rightarrow$ oracle-bearing $\rightarrow$ reproducible $\rightarrow$ non-duplicate $\rightarrow$ minimized $\rightarrow$ stable/nightly $\rightarrow$ promoted.",
        "",
        "% Insert this block in Section 4.7 (Candidate Case Analysis).",
        r"\begin{table}[H]",
        r"\centering\scriptsize",
        r"\caption{Structured candidate-family ledger. Pending means that the required evidence is absent from the local archive.}",
        r"\label{tab:candidate_ledger_structured}",
        r"\begin{tabularx}{\linewidth}{@{}Yccccccc@{}}",
        r"\toprule",
        r"\textbf{Candidate/family} & \textbf{Repro.} & \textbf{Dup.} & \textbf{Min.} & \textbf{Stable} & \textbf{Nightly} & \textbf{Promoted} & \textbf{Evidence} \\",
        r"\midrule",
    ])
    for row in ledger_rows:
        fields = [
            tex_escape(row["candidate_family"]), status[row["reproduced"]],
            status[row["duplicate_checked"]], status[row["minimized"]],
            status[row["stable_tested"]], status[row["nightly_tested"]],
            status[row["promoted"]], "Artifact" if row["evidence_level"] == "workspace_artifact" else "Paper",
        ]
        lines.append(" & ".join(fields) + r" \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabularx}",
        r"\end{table}",
        "",
        r"\noindent All five ledger rows have recorded reproduction claims; two rows are backed by independent files in the current workspace and three are currently paper-only transcriptions. Three are minimized, one is partially minimized, and one is not minimized. Duplicate checking is partial for four rows and absent for one. Nightly/main testing is recorded for two rows and pending for three. No row has a recorded completed Vn promotion; this is zero recorded promotions, not evidence that every candidate failed novelty review.",
        "",
        "% Insert this paragraph in Section 5.3 (Reproducibility and Artifact Availability).",
        r"\noindent The artifact contains a standard-library JSONL normalizer, the ordered tri-state funnel schema, a structured candidate ledger in JSONL/CSV, archived campaign counters, unit tests, and generated JSON/CSV/\LaTeX{} summaries. A source audit found that the Atlas counts (7,275 normalized records, 5,868 unique issues, 2,653 clusters; 5,285 PyTorch and 1,990 TensorFlow records) are internally consistent but cannot be independently recomputed because the raw Atlas dataset and its manifest are absent from the current workspace. They are therefore identified as paper-reported snapshot counts. Atlas duplicate-removal and planning-intervention counts remain null pending an enabled-versus-disabled retrieval run.",
        "",
    ])
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    lines = [
        "# Archived Vn Gate and DL-Issue Atlas evidence",
        "",
        "> Missing evidence is reported as missing, never as zero. Counts from different campaign denominators are not pooled.",
        "",
        "## Funnel evidence coverage",
        "",
        "| Stage | Campaigns with a logged value | Campaigns missing the value |",
        "|---|---:|---:|",
    ]
    for stage, counts in report["funnel_field_coverage"].items():
        lines.append(f"| `{stage}` | {counts['campaigns_logged']} | {counts['campaigns_missing']} |")
    ledger = report["candidate_ledger"]
    lines.extend([
        "",
        "## Candidate ledger",
        "",
        f"The structured ledger contains {ledger['rows']} candidate-family rows. Recorded completed Vn promotions: **{ledger['fully_promoted_candidates']}**.",
        "",
        f"Duplicate-check states: `{json.dumps(ledger['duplicate_check_states'], sort_keys=True)}`.",
        f"Promotion states: `{json.dumps(ledger['promotion_states'], sort_keys=True)}`.",
        "",
        "## DL-Issue Atlas",
        "",
    ])
    atlas = report["atlas"]
    lines.extend([
        f"The paper-reported snapshot has {atlas['records']:,} normalized records, {atlas['unique_issues']:,} unique issues, and {atlas['canonical_clusters']:,} canonical clusters.",
        f"This is {atlas['records_per_cluster']:.2f} records and {atlas['unique_issues_per_cluster']:.2f} unique issues per canonical cluster on average.",
        f"PyTorch contributes {atlas['pytorch_record_share']:.1%} of records and TensorFlow {atlas['tensorflow_record_share']:.1%}.",
        "",
        "The archive does **not** contain an enabled-vs-disabled retrieval intervention, so duplicate candidates detected by Atlas and Atlas-guided candidates remain `null` rather than zero.",
        "The raw Atlas dataset/manifest is also absent from this workspace. The counts are arithmetically consistent (5,285 + 1,990 = 7,275) but not independently recomputed; the audit status is `internally_consistent_not_independently_recomputed`.",
        "",
        "## Unsupported aggregate claims",
        "",
    ])
    lines.extend(f"- {claim}" for claim in report["claims_not_supported"])
    return "\n".join(lines) + "\n"


def main() -> None:
    report = build()
    ledger_rows = load_ledger()
    vn_funnel.write_json(HERE / "archive_evidence_report.json", report)
    (HERE / "archive_evidence_report.md").write_text(render_markdown(report), encoding="utf-8")
    write_candidate_csv(ledger_rows)
    (HERE / "paper_snippets.tex").write_text(render_latex(report, ledger_rows), encoding="utf-8")
    print("Wrote archive report, candidate CSV, and paper_snippets.tex")


if __name__ == "__main__":
    main()
