"""Freeze a recovered DL-Issue Atlas export into a verifiable source manifest."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from collect_atlas_intervention import _record_count, file_sha256


def build_manifest(
    dataset: Path,
    dataset_format: str,
    snapshot_id: str,
    created_by: str,
    source_system: str,
    export_command: str,
    created_utc: str | None = None,
) -> dict:
    if not dataset.is_file():
        raise ValueError(f"Atlas dataset does not exist: {dataset}")
    provenance = {
        "snapshot_id": snapshot_id,
        "created_by": created_by,
        "source_system": source_system,
        "export_command": export_command,
    }
    if any(not isinstance(value, str) or not value.strip() for value in provenance.values()):
        raise ValueError("snapshot and provenance arguments must be non-empty")
    timestamp = created_utc or datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_utc must include a timezone")
    records = _record_count(dataset, dataset_format)
    if records < 1:
        raise ValueError("Atlas dataset is empty")
    return {
        "schema_version": "trdgl_atlas_source_manifest_v1",
        "snapshot_id": snapshot_id,
        "evidence_label": "campaign",
        "dataset_file_name": dataset.name,
        "dataset_format": dataset_format,
        "dataset_sha256": file_sha256(dataset),
        "dataset_bytes": dataset.stat().st_size,
        "record_count": records,
        "created_utc": timestamp,
        "created_by": created_by,
        "source_system": source_system,
        "export_command": export_command,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--format", choices=("jsonl", "json", "csv"), required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--export-command", required=True)
    parser.add_argument("--created-utc")
    args = parser.parse_args()
    manifest = build_manifest(
        args.dataset, args.format, args.snapshot_id, args.created_by,
        args.source_system, args.export_command, args.created_utc,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset": str(args.dataset), "manifest": str(args.output),
        "sha256": manifest["dataset_sha256"], "records": manifest["record_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
