"""Build the deterministic, non-empirical Atlas protocol validation bundle."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import collect_atlas_intervention as collector


HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parents[1]
OUTPUT = HERE / "validation_output"
EVENTS = HERE / "testdata" / "validation_events.jsonl"
AUDIT = HERE.parent / "vn_funnel" / "atlas_snapshot.json"
SUMMARY = OUTPUT / "summary.validation.json"
MANIFEST = OUTPUT / "validation_manifest.json"
SEEDS = [3407, 7711, 12011, 19001, 27103]


def relative(path: Path) -> str:
    return path.relative_to(PAPER_ROOT).as_posix() if path.is_relative_to(PAPER_ROOT) else path.as_posix()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = collector.summarize(EVENTS, AUDIT, SEEDS)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    command = [sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_*.py", "-v"]
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", check=False)
    test_log = completed.stdout + completed.stderr
    match = re.search(r"Ran (\d+) tests?", test_log)
    if completed.returncode != 0:
        raise RuntimeError(f"Atlas contract tests failed:\n{test_log}")

    artifact_paths = [
        HERE / "collect_atlas_intervention.py",
        HERE / "atlas_intervention_event.schema.json",
        HERE / "atlas_intervention_summary.schema.json",
        HERE / "atlas_source_manifest.schema.json",
        HERE / "source_recovery_search.md",
        HERE / "test_atlas_intervention.py",
        HERE / "test_two_seed_atlas_checkpoint.py",
        HERE / "verify_two_seed_atlas_checkpoint.py",
        HERE / "two_seed_checkpoint" / "atlas_blocker_manifest.json",
        EVENTS,
        AUDIT,
        SUMMARY,
    ]
    manifest = {
        "schema_version": "trdgl_atlas_validation_bundle_v1",
        "evidence_label": "validation_only",
        "purpose": "Executable contract validation; not an Atlas effectiveness experiment.",
        "artifact_sha256": {relative(path): collector.file_sha256(path) for path in artifact_paths},
        "contract_tests": {
            "command": "python -m unittest discover -s experiments/atlas_intervention -p test_*.py -v",
            "result": "pass",
            "test_count": int(match.group(1)) if match else None,
        },
        "summary_path": relative(SUMMARY),
        "summary_ready_for_paper_result": summary["ready_for_paper_result"],
        "summary_blockers": summary["blockers"],
        "raw_atlas_included": False,
        "independent_atlas_manifest_included": False,
        "effectiveness_claim_allowed": False,
        "claim_boundary": "Synthetic fixture counts validate aggregation only and must not be reported as empirical counts or effect sizes.",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "pass",
        "manifest": relative(MANIFEST),
        "tests": manifest["contract_tests"],
        "ready_for_paper_result": False,
        "effectiveness_claim_allowed": False,
    }, indent=2))


if __name__ == "__main__":
    main()
