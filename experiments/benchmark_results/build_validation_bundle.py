"""Build the non-empirical benchmark and multi-shard contract bundle."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import collect_benchmark_results as collector


HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parents[1]
WORKSPACE = PAPER_ROOT.parent
OUTPUT = HERE / "validation_output"
NOTEBOOK = HERE.parent / "benchmark_120" / "trdgl_fair_benchmark_120.ipynb"
SMOKE = WORKSPACE / "tmp" / "colab_smoke_4baseline" / "events_latest.jsonl"


def relative(path: Path) -> str:
    try:
        return path.relative_to(WORKSPACE).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT / "summary.validation.json"
    cells_path = OUTPUT / "baseline_group_seed.validation.csv"
    coverage_path = OUTPUT / "event_coverage.validation.csv"
    summary, cells = collector.summarize(SMOKE, NOTEBOOK, "validation_only")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    collector.write_cells(cells_path, cells)
    collector.write_cells(coverage_path, collector.build_coverage_rows(NOTEBOOK, SMOKE))

    command = [sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_*.py", "-v"]
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", check=False)
    log = completed.stdout + completed.stderr
    match = re.search(r"Ran (\d+) tests?", log)
    if completed.returncode != 0:
        raise RuntimeError(f"benchmark contract tests failed:\n{log}")

    artifacts = [
        HERE / "collect_benchmark_results.py",
        HERE / "collect_benchmark_campaign.py",
        HERE / "audit_checkpoint_provenance.py",
        HERE / "benchmark_result_summary.schema.json",
        HERE / "campaign_shard_index.schema.json",
        HERE / "campaign_shards.template.json",
        HERE / "test_benchmark_results.py",
        NOTEBOOK,
        SMOKE,
        summary_path,
        cells_path,
        coverage_path,
    ]
    manifest = {
        "schema_version": "trdgl_benchmark_validation_bundle_v1",
        "evidence_label": "validation_only",
        "purpose": "Executable single-stream and five-shard aggregation contract validation; not a completed benchmark campaign.",
        "artifact_sha256": {relative(path): collector.sha256_file(path) for path in artifacts},
        "contract_tests": {
            "command": "python -m unittest discover -s experiments/benchmark_results -p test_*.py -v",
            "result": "pass",
            "test_count": int(match.group(1)) if match else None,
        },
        "smoke_observed_events": summary["coverage"]["observed_event_count"],
        "full_benchmark_complete": summary["full_benchmark_complete"],
        "ready_for_paper_result": summary["ready_for_paper_result"],
        "claim_boundary": "Synthetic complete-shard tests validate the gate only; smoke/checkpoint counts must not be promoted to a completed campaign.",
    }
    manifest_path = OUTPUT / "validation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "pass", "manifest": relative(manifest_path),
        "tests": manifest["contract_tests"], "ready_for_paper_result": False,
    }, indent=2))


if __name__ == "__main__":
    main()
