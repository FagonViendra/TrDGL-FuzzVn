#!/usr/bin/env python3
"""Refresh generation-error artifacts only when a JSONL checkpoint changes.

With ``--watch`` the command polls continuously until interrupted.  It does
not touch a model runtime or GPU; it only replays static and recorded harness
evidence from immutable byte snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import analyze_generation_errors as analyzer_module


CATEGORIES = analyzer_module.CATEGORIES
LOADED_ANALYZER_SHA256 = analyzer_module.LOADED_ANALYZER_SHA256
VERSION = analyzer_module.VERSION
analyze = analyzer_module.analyze


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_CAMPAIGN = REPO_ROOT / "tmp" / "seed3407_progress.jsonl"
DEFAULT_SMOKE = REPO_ROOT / "tmp" / "colab_smoke_4baseline" / "events_latest.jsonl"
DEFAULT_OUTPUT = HERE / "validation_output"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_paths(campaign: Path, smoke: Path | None) -> list[Path]:
    paths = [campaign]
    if smoke is not None and smoke.is_file():
        paths.append(smoke)
    return paths


def current_signature(paths: list[Path]) -> tuple[str, dict[str, str]]:
    hashes = {str(path.resolve()): sha256(path) for path in paths}
    digest = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest, hashes


def manifest_state(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "analysis_manifest.json"
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        return {
            "source_hashes": {
                str(Path(s["path"]).resolve()): s["sha256"] for s in manifest.get("sources", [])
            },
            "schema_version": manifest.get("schema_version"),
            "analyzer_sha256": manifest.get("analyzer_sha256"),
            "categories": manifest.get("categories"),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}


class OutputLock:
    def __init__(self, output_dir: Path, stale_seconds: float = 3600.0):
        self.path = output_dir / ".refresh.lock"
        self.stale_seconds = stale_seconds
        self.fd: int | None = None
        self.token = f"pid={os.getpid()} nonce={uuid.uuid4().hex}"

    def __enter__(self) -> "OutputLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > self.stale_seconds:
            self.path.unlink()
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"another refresh owns {self.path}") from exc
        os.write(
            self.fd,
            f"{self.token} utc={datetime.now(timezone.utc).isoformat()}\n".encode(),
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
        # A stale-lock recovery may have replaced this path while the original
        # owner was still alive.  Never remove a successor's lock.
        try:
            contents = self.path.read_text(encoding="utf-8")
            if contents.startswith(self.token + " "):
                self.path.unlink()
        except FileNotFoundError:
            pass


def publish_staged_outputs(stage_dir: Path, output_dir: Path, outputs: list[str]) -> None:
    """Publish complete files atomically, with the manifest as commit marker."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in outputs:
        source = stage_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"staged output is missing: {source}")
    for name in outputs:
        os.replace(stage_dir / name, output_dir / name)
    os.replace(stage_dir / "analysis_manifest.json", output_dir / "analysis_manifest.json")


def append_history(output_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    history_path = output_dir / "checkpoint_history.jsonl"
    source_hashes = {source["path"]: source["sha256"] for source in manifest["sources"]}
    signature = hashlib.sha256(
        json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    analysis_signature = hashlib.sha256(
        f"{signature}:{manifest['schema_version']}:{manifest['analyzer_sha256']}".encode("utf-8")
    ).hexdigest()
    existing_signatures: set[str] = set()
    if history_path.is_file():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    value = json.loads(line).get("analysis_signature")
                    if value:
                        existing_signatures.add(value)
                except json.JSONDecodeError:
                    continue

    counts: Counter[tuple[str, str]] = Counter()
    events_path = output_dir / "event_classification.jsonl"
    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        counts[(event["source_role"], event["baseline"])] += 1
    entry = {
        "refreshed_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_signature": signature,
        "analysis_signature": analysis_signature,
        "schema_version": manifest["schema_version"],
        "analyzer_sha256": manifest["analyzer_sha256"],
        "sources": manifest["sources"],
        "classified_records": manifest["classified_records"],
        "counts_by_role_and_baseline": {
            f"{role}:{baseline}": count for (role, baseline), count in sorted(counts.items())
        },
    }
    if analysis_signature not in existing_signatures:
        with history_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def refresh_once(
    campaign: Path,
    smoke: Path | None,
    output_dir: Path,
    expected_per_baseline: int = 120,
    expected_per_group: int = 12,
    force: bool = False,
) -> tuple[bool, dict[str, Any]]:
    paths = input_paths(campaign, smoke)
    if not campaign.is_file():
        raise FileNotFoundError(campaign)
    with OutputLock(output_dir):
        _, before = current_signature(paths)
        prior = manifest_state(output_dir)
        current = (
            prior.get("source_hashes") == before
            and prior.get("schema_version") == VERSION
            and prior.get("analyzer_sha256") == LOADED_ANALYZER_SHA256
            and prior.get("categories") == list(CATEGORIES)
        )
        if not force and current:
            return False, {"status": "no_change", "source_hashes": before}
        stage_dir = output_dir.parent / f".{output_dir.name}.refresh-{uuid.uuid4().hex}"
        try:
            manifest = analyze(paths, stage_dir, expected_per_baseline, expected_per_group)
            prior_history = output_dir / "checkpoint_history.jsonl"
            if prior_history.is_file():
                shutil.copyfile(prior_history, stage_dir / "checkpoint_history.jsonl")
            history = append_history(stage_dir, manifest)
            manifest["incremental_refresh"] = {
                "history_file": "checkpoint_history.jsonl",
                "checkpoint_signature": history["checkpoint_signature"],
                "publish_policy": "staged files; analysis_manifest.json replaced last",
            }
            if "checkpoint_history.jsonl" not in manifest["outputs"]:
                manifest["outputs"].append("checkpoint_history.jsonl")
            (stage_dir / "analysis_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            publish_staged_outputs(stage_dir, output_dir, manifest["outputs"])
            return True, history
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--smoke", type=Path, default=DEFAULT_SMOKE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-records-per-baseline", type=int, default=120)
    parser.add_argument("--expected-records-per-group", type=int, default=12)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--watch", action="store_true", help="poll forever until Ctrl+C")
    parser.add_argument("--poll-seconds", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global CATEGORIES, LOADED_ANALYZER_SHA256, VERSION, analyze, analyzer_module
    args = parse_args(argv)
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")
    while True:
        try:
            current_analyzer_hash = sha256(Path(analyze.__code__.co_filename))
            if current_analyzer_hash != LOADED_ANALYZER_SHA256:
                if args.watch:
                    print(
                        f"[{datetime.now(timezone.utc).isoformat()}] RELOAD analyzer source changed",
                        flush=True,
                    )
                    analyzer_module = importlib.reload(analyzer_module)
                    CATEGORIES = analyzer_module.CATEGORIES
                    LOADED_ANALYZER_SHA256 = analyzer_module.LOADED_ANALYZER_SHA256
                    VERSION = analyzer_module.VERSION
                    analyze = analyzer_module.analyze
                else:
                    raise RuntimeError("analyzer source changed after import; rerun the command")
            updated, detail = refresh_once(
                args.campaign,
                args.smoke,
                args.output_dir,
                args.expected_records_per_baseline,
                args.expected_records_per_group,
                args.force,
            )
            stamp = datetime.now(timezone.utc).isoformat()
            if updated:
                print(f"[{stamp}] UPDATED {detail['checkpoint_signature']} records={detail['classified_records']}", flush=True)
            elif not args.watch:
                print(f"[{stamp}] NO_CHANGE", flush=True)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            if not args.watch:
                raise
            print(f"[{datetime.now(timezone.utc).isoformat()}] RETRY {type(exc).__name__}: {exc}", flush=True)
        if not args.watch:
            return 0
        args.force = False
        try:
            time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            print("watch stopped", flush=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
