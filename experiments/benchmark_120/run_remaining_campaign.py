"""Run the four remaining TrDGL benchmark seed shards through Colab CLI.

This is an orchestration layer around the frozen benchmark notebook.  It does
not edit or transform the notebook, prompts, models, decoding settings, event
schema, or execution harness.  The optimization is operational:

* one T4 session is reused across seeds so the model stage survives;
* event writes stay on the Colab local SSD and are downloaded periodically;
* every downloaded snapshot is validated before it replaces the local backup;
* interrupted runs resume from the append-only JSONL without duplicate work;
* concise progress, ETA, hashes, and a final handoff ZIP are produced locally.

Default Windows usage from any PowerShell directory:

    python "C:\\Users\\fagon\\OneDrive\\Documents\\New project 2\\TrDGL-FuzzVn_paper\\experiments\\benchmark_120\\run_remaining_campaign.py"

Rerun the same command after an interruption.  To validate the runner without
creating a Colab session:

    python run_remaining_campaign.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import base64
import collections
import copy
import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARK_DIR = SCRIPT_PATH.parent
WORKSPACE = SCRIPT_PATH.parents[3]
FROZEN_NOTEBOOK = BENCHMARK_DIR / "trdgl_fair_benchmark_120.ipynb"
REFERENCE_MANIFEST = BENCHMARK_DIR / "checkpoints" / "seed3407_480" / "run_manifest.json"
REFERENCE_EVENTS = BENCHMARK_DIR / "checkpoints" / "seed3407_480" / "events.checkpoint.jsonl"
DEFAULT_OUTPUT_ROOT = WORKSPACE / "tmp" / "trdgl_campaign_continuation"

SEEDS = [3407, 7711, 12011, 19001, 27103]
DEFAULT_REMAINING_INDICES = [1, 2, 3, 4]
BASELINES = ("B0", "B1", "B2", "B3")
EXPECTED_EVENTS_PER_SEED = 480
EXPECTED_EVENTS_PER_BASELINE = 120
EXPECTED_NOTEBOOK_SHA256 = "f223245216f4861b329b7497720032ec7dd61548a0ef4cd8818ece8ba9f58a1d"
EXPECTED_CODE_SOURCE_SHA256 = "a070d6518e2876ee56d88de676236f59d61f6cd10fc7a20a0e301ffa8ed9c650"
EXPECTED_RUNNER_VERSION = "four_baseline_runner_v1"
EXPECTED_MANIFEST_SHA256 = "d9de15ca10bdd4abef2106c58b661197f69d1f278f87eec2b6eb56845f4facac"
REMOTE_CACHE_LOCAL = "/content/trdgl_shared_cache"
REMOTE_CACHE_DRIVE = "/content/drive/MyDrive/TrDGL-FuzzVn/cache"


class RunnerError(RuntimeError):
    """Base error for a fail-closed orchestration decision."""


class SnapshotTransientError(RunnerError):
    """A remote file was observed while it was being copied or appended."""


class EvidenceContractError(RunnerError):
    """Persisted evidence violates the frozen benchmark contract."""


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def notebook_contract(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    sources = [
        "".join(cell.get("source", []))
        for cell in document.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
    versions: list[str] = []
    for source in sources:
        marker = "RUNNER_VERSION = "
        for line in source.splitlines():
            if line.startswith(marker):
                versions.append(line[len(marker) :].strip().strip("'\""))
    if len(versions) != 1:
        raise EvidenceContractError(
            f"expected one RUNNER_VERSION literal, found {versions}"
        )
    return {
        "code_sources": sources,
        "code_source_sha256": canonical_hash(sources),
        "runner_version": versions[0],
    }


@functools.lru_cache(maxsize=1)
def load_frozen_manifest(path: Path = FROZEN_NOTEBOOK) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    encoded: str | None = None
    declared_hash: str | None = None
    for cell in document.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        tree = ast.parse("".join(cell.get("source", [])))
        for node in tree.body:
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                continue
            name = node.targets[0].id
            if name == "MANIFEST_ZLIB_BASE64":
                encoded = ast.literal_eval(node.value)
            elif name == "FROZEN_CANONICAL_SHA256":
                declared_hash = ast.literal_eval(node.value)
    if not encoded or not declared_hash:
        raise EvidenceContractError("frozen notebook manifest literals are missing")
    manifest = json.loads(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))
    if canonical_hash(manifest) != declared_hash:
        raise EvidenceContractError("embedded benchmark manifest hash mismatch")
    if declared_hash != EXPECTED_MANIFEST_SHA256:
        raise EvidenceContractError("embedded benchmark manifest is not v1 frozen input")
    return manifest


@functools.lru_cache(maxsize=len(SEEDS))
def expected_tasks_for_seed(seed: int) -> dict[str, dict[str, Any]]:
    manifest = load_frozen_manifest()
    try:
        seed_index = manifest["generation_seeds"].index(seed)
    except ValueError as exc:
        raise EvidenceContractError(f"seed {seed} is outside the frozen manifest") from exc
    baseline_ids = manifest["baseline_ids"]
    entries = [
        {"group": group["id"], "api": api}
        for group in manifest["groups"]
        for api in group["apis"]
    ]
    expected: dict[str, dict[str, Any]] = {}
    for api_index, entry in enumerate(entries):
        rotation = (api_index + seed_index) % len(baseline_ids)
        baseline_order = baseline_ids[rotation:] + baseline_ids[:rotation]
        task_id = f"{manifest['benchmark_id']}|{entry['api']}|{seed}"
        expected[task_id] = {
            "task_id": task_id,
            "api": entry["api"],
            "api_group": entry["group"],
            "api_index": api_index,
            "generation_seed": seed,
            "ab_order": (
                "B2_then_B3"
                if (seed_index < 4 and seed_index % 2 == 0)
                or (seed_index == 4 and api_index < 60)
                else "B3_then_B2"
            ),
            "logical_baseline_order": baseline_order,
        }
    if len(expected) != EXPECTED_EVENTS_PER_BASELINE:
        raise EvidenceContractError("frozen manifest does not contain 120 tasks per seed")
    return expected


def verify_frozen_inputs() -> dict[str, Any]:
    if not FROZEN_NOTEBOOK.is_file():
        raise FileNotFoundError(FROZEN_NOTEBOOK)
    if not REFERENCE_MANIFEST.is_file():
        raise FileNotFoundError(REFERENCE_MANIFEST)
    notebook_sha = sha256_file(FROZEN_NOTEBOOK)
    if notebook_sha != EXPECTED_NOTEBOOK_SHA256:
        raise EvidenceContractError(
            "frozen notebook byte hash changed: "
            f"expected {EXPECTED_NOTEBOOK_SHA256}, observed {notebook_sha}"
        )
    contract = notebook_contract(FROZEN_NOTEBOOK)
    if contract["code_source_sha256"] != EXPECTED_CODE_SOURCE_SHA256:
        raise EvidenceContractError(
            "frozen notebook code-cell hash changed: "
            f"expected {EXPECTED_CODE_SOURCE_SHA256}, "
            f"observed {contract['code_source_sha256']}"
        )
    if contract["runner_version"] != EXPECTED_RUNNER_VERSION:
        raise EvidenceContractError(
            f"runner version changed: {contract['runner_version']}"
        )
    reference = json.loads(REFERENCE_MANIFEST.read_text(encoding="utf-8"))
    if reference.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        raise EvidenceContractError("reference manifest uses the wrong benchmark hash")
    manifest = load_frozen_manifest()
    if manifest.get("generation_seeds") != SEEDS:
        raise EvidenceContractError("embedded generation-seed order changed")
    return {
        "notebook": contract,
        "reference_manifest": reference,
        "benchmark_manifest": manifest,
    }


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path, json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "unknown"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


@dataclass(frozen=True)
class EventSnapshot:
    path: Path
    seed: int
    count: int
    counts: dict[str, int]
    sha256: str | None
    signatures: tuple[str, ...]
    prompt_mismatch_count: int
    last_baseline: str | None
    last_api: str | None
    last_finished_utc: str | None
    first_started_utc: str | None

    @property
    def complete(self) -> bool:
        return self.count == EXPECTED_EVENTS_PER_SEED and all(
            self.counts.get(baseline, 0) == EXPECTED_EVENTS_PER_BASELINE
            for baseline in BASELINES
        )


def empty_snapshot(path: Path, seed: int) -> EventSnapshot:
    return EventSnapshot(
        path=path,
        seed=seed,
        count=0,
        counts={baseline: 0 for baseline in BASELINES},
        sha256=None,
        signatures=(),
        prompt_mismatch_count=0,
        last_baseline=None,
        last_api=None,
        last_finished_utc=None,
        first_started_utc=None,
    )


def read_event_rows(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotTransientError(f"non-UTF-8 event snapshot: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotTransientError(
                f"JSONL line {line_number} is incomplete or malformed: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise EvidenceContractError(f"JSONL line {line_number} is not an object")
        rows.append(row)
    return data, rows


def inspect_events(path: Path, seed: int) -> EventSnapshot:
    if not path.is_file():
        return empty_snapshot(path, seed)
    data, rows = read_event_rows(path)
    counts: collections.Counter[str] = collections.Counter()
    identities: set[tuple[str, str]] = set()
    signatures: set[str] = set()
    prompts: dict[str, dict[str, str]] = collections.defaultdict(dict)
    expected_tasks = expected_tasks_for_seed(seed)
    required = {
        "baseline",
        "task_id",
        "api",
        "api_group",
        "api_index",
        "generation_seed",
        "ab_order",
        "logical_baseline_order",
        "prompt_sha256",
        "run_signature",
        "raw_output_sha256",
        "raw_generation",
    }
    for index, row in enumerate(rows, start=1):
        missing = sorted(required - set(row))
        if missing:
            raise EvidenceContractError(
                f"event row {index} is missing required fields: {missing}"
            )
        baseline = row["baseline"]
        if baseline not in BASELINES:
            raise EvidenceContractError(
                f"event row {index} has unexpected baseline {baseline!r}"
            )
        if row["generation_seed"] != seed:
            raise EvidenceContractError(
                f"event row {index} has seed {row['generation_seed']}, expected {seed}"
            )
        task_id = row["task_id"]
        if task_id not in expected_tasks:
            raise EvidenceContractError(
                f"event row {index} has task outside the frozen seed shard: {task_id}"
            )
        expected = expected_tasks[task_id]
        for field in (
            "api",
            "api_group",
            "api_index",
            "generation_seed",
            "ab_order",
            "logical_baseline_order",
        ):
            if row[field] != expected[field]:
                raise EvidenceContractError(
                    f"event row {index} field {field} differs from frozen task: "
                    f"expected {expected[field]!r}, observed {row[field]!r}"
                )
        identity = (baseline, task_id)
        if identity in identities:
            raise EvidenceContractError(f"duplicate event identity: {identity}")
        identities.add(identity)
        counts[baseline] += 1
        if counts[baseline] > EXPECTED_EVENTS_PER_BASELINE:
            raise EvidenceContractError(
                f"baseline {baseline} exceeds {EXPECTED_EVENTS_PER_BASELINE} rows"
            )
        signature = row["run_signature"]
        if not isinstance(signature, str) or len(signature) != 64:
            raise EvidenceContractError(f"invalid run signature on row {index}")
        signatures.add(signature)
        for hash_field in ("prompt_sha256", "raw_output_sha256"):
            value = row[hash_field]
            if not isinstance(value, str) or len(value) != 64:
                raise EvidenceContractError(
                    f"invalid {hash_field} on event row {index}"
                )
        if baseline in {"B2", "B3"}:
            prompts[task_id][baseline] = row.get("prompt_sha256")
        if row.get("raw_generation") is not True:
            raise EvidenceContractError(f"raw generation missing on row {index}")
    if len(rows) > EXPECTED_EVENTS_PER_SEED:
        raise EvidenceContractError(
            f"snapshot has {len(rows)} rows; maximum is {EXPECTED_EVENTS_PER_SEED}"
        )
    if len(signatures) > 1:
        raise EvidenceContractError(
            f"snapshot mixes run signatures: {sorted(signatures)}"
        )
    prompt_mismatches = sum(
        1
        for pair in prompts.values()
        if set(pair) == {"B2", "B3"} and pair["B2"] != pair["B3"]
    )
    normalized_counts = {baseline: counts.get(baseline, 0) for baseline in BASELINES}
    first = rows[0] if rows else {}
    last = rows[-1] if rows else {}
    return EventSnapshot(
        path=path,
        seed=seed,
        count=len(rows),
        counts=normalized_counts,
        sha256=sha256_bytes(data),
        signatures=tuple(sorted(signatures)),
        prompt_mismatch_count=prompt_mismatches,
        last_baseline=last.get("baseline"),
        last_api=last.get("api"),
        last_finished_utc=last.get("finished_utc"),
        first_started_utc=first.get("started_utc"),
    )


def parse_seed_indices(value: str) -> list[int]:
    pieces = [piece.strip() for piece in value.split(",") if piece.strip()]
    if not pieces:
        raise argparse.ArgumentTypeError("at least one seed index is required")
    try:
        indices = [int(piece) for piece in pieces]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seed indices must be integers") from exc
    if len(indices) != len(set(indices)):
        raise argparse.ArgumentTypeError("seed indices must be unique")
    invalid = [index for index in indices if index not in range(len(SEEDS))]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"seed indices must be in 0..{len(SEEDS) - 1}: {invalid}"
        )
    return indices


def summarize_error(*parts: str) -> str:
    text = "\n".join(part for part in parts if part)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    needles = (
        "TooManyAssignmentsError",
        "ResourceExhausted",
        "Service Unavailable",
        "Precondition Failed",
        "quota",
        "authentication",
        "No active sessions",
        "Traceback",
    )
    for needle in needles:
        for line in reversed(lines):
            if needle.lower() in line.lower():
                return line[:700]
    return (lines[-1] if lines else "unknown Colab CLI error")[:700]


class ColabCLI:
    def __init__(self, distro: str, binary: str, session: str) -> None:
        self.distro = distro
        self.binary = binary
        self.session = session

    def _base(self) -> list[str]:
        return [
            "wsl.exe",
            "-d",
            self.distro,
            "--",
            self.binary,
            "--auth=oauth2",
        ]

    def command(self, *args: str) -> list[str]:
        return self._base() + list(args)

    def run(
        self,
        *args: str,
        timeout: float = 180,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = self.command(*args)
        try:
            completed = subprocess.run(
                command,
                cwd=str(WORKSPACE),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            completed = subprocess.CompletedProcess(
                command,
                124,
                stdout,
                stderr + f"\nColab CLI command timed out after {timeout}s",
            )
        if check and completed.returncode != 0:
            raise RunnerError(summarize_error(completed.stderr, completed.stdout))
        return completed

    def popen(self, *args: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            self.command(*args),
            cwd=str(WORKSPACE),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )

    def wsl_path(self, path: Path) -> str:
        completed = subprocess.run(
            [
                "wsl.exe",
                "-d",
                self.distro,
                "--",
                "wslpath",
                "-a",
                str(path.resolve()),
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
            timeout=30,
        )
        return completed.stdout.strip()

    def status(self) -> str:
        completed = self.run("status", "-s", self.session, timeout=60)
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        if completed.returncode != 0 or "no active sessions" in text:
            return "missing"
        if "status: idle" in text:
            return "idle"
        if "status: busy" in text or "status: running" in text:
            return "busy"
        return "unknown"

    def download(self, remote: str, local: Path, timeout: float = 180) -> bool:
        local.parent.mkdir(parents=True, exist_ok=True)
        completed = self.run(
            "download",
            "-s",
            self.session,
            remote,
            self.wsl_path(local),
            timeout=timeout,
        )
        return completed.returncode == 0 and local.is_file()

    def upload(self, local: Path, remote: str, timeout: float = 300) -> None:
        self.run(
            "upload",
            "-s",
            self.session,
            self.wsl_path(local),
            remote,
            timeout=timeout,
            check=True,
        )


class CampaignRunner:
    def __init__(self, args: argparse.Namespace, frozen: dict[str, Any]) -> None:
        self.args = args
        self.frozen = frozen
        self.output_root = args.output_root.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.output_root / "campaign_progress.log"
        self.state_path = self.output_root / "campaign_status.json"
        self.lock_path = self.output_root / ".runner.lock"
        self.print_lock = threading.Lock()
        self.cli = ColabCLI(args.wsl_distro, args.colab_bin, args.session)
        self.cache_root = REMOTE_CACHE_LOCAL
        self.drive_mount_attempted = False
        self.current_process: subprocess.Popen[str] | None = None

    def log(self, message: str) -> None:
        line = f"{utc_now()} {message}"
        with self.print_lock:
            print(line, flush=True)
            with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")

    def write_state(self, **fields: Any) -> None:
        atomic_write_json(
            self.state_path,
            {
                "schema_version": "trdgl_campaign_live_status_v1",
                "updated_utc": utc_now(),
                "session": self.args.session,
                "seed_indices": self.args.seed_indices,
                "seeds": [SEEDS[index] for index in self.args.seed_indices],
                **fields,
            },
        )

    def acquire_lock(self) -> None:
        if self.lock_path.exists():
            try:
                old = json.loads(self.lock_path.read_text(encoding="utf-8"))
                old_pid = int(old.get("pid"))
                os.kill(old_pid, 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self.lock_path.unlink(missing_ok=True)
            else:
                raise RunnerError(
                    f"another runner process is active (PID {old_pid}); "
                    f"lock={self.lock_path}"
                )
        descriptor = os.open(
            self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"pid": os.getpid(), "created_utc": utc_now()}, handle)
            handle.write("\n")

    def release_lock(self) -> None:
        self.lock_path.unlink(missing_ok=True)

    def seed_dir(self, seed: int) -> Path:
        path = self.output_root / f"seed{seed}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def remote_dir(seed: int) -> str:
        return f"/content/trdgl_benchmark_seed_{seed}"

    def remote_file(self, seed: int, name: str) -> str:
        return f"{self.remote_dir(seed)}/{name}"

    def ensure_session(self) -> str:
        while True:
            status = self.cli.status()
            if status in {"idle", "busy"}:
                return status
            self.log(
                f"Colab session {self.args.session!r} is unavailable; requesting T4"
            )
            completed = self.cli.run(
                "new",
                "-s",
                self.args.session,
                "--gpu",
                "T4",
                timeout=240,
            )
            status = self.cli.status()
            if status in {"idle", "busy"}:
                self.log(f"T4 session ready: status={status}")
                self.drive_mount_attempted = False
                return status
            reason = summarize_error(completed.stderr, completed.stdout)
            self.log(
                f"T4 not assigned yet: {reason}; retrying in "
                f"{self.args.assignment_retry_seconds}s"
            )
            self.write_state(
                status="waiting_for_t4",
                reason=reason,
                retry_seconds=self.args.assignment_retry_seconds,
            )
            time.sleep(self.args.assignment_retry_seconds)

    def configure_cache(self) -> None:
        if self.drive_mount_attempted:
            return
        self.drive_mount_attempted = True
        if self.args.cache_mode == "local":
            self.cache_root = REMOTE_CACHE_LOCAL
            self.log("Using Colab local SSD model cache")
            return
        self.log("Mounting Google Drive for persistent verified model cache")
        completed = self.cli.run(
            "drivemount",
            "-s",
            self.args.session,
            "/content/drive",
            timeout=240,
        )
        if completed.returncode == 0:
            self.cache_root = REMOTE_CACHE_DRIVE
            self.log("Drive cache ready; local GGUF stage will be reused across seeds")
        else:
            self.cache_root = REMOTE_CACHE_LOCAL
            reason = summarize_error(completed.stderr, completed.stdout)
            self.log(f"Drive mount unavailable ({reason}); falling back to local cache")

    def build_preflight(self, seed_index: int, seed_dir: Path) -> Path:
        seed = SEEDS[seed_index]
        reference = self.frozen["reference_manifest"]
        expected_environment = {
            "torch_version": reference["torch_version"],
            "torch_cuda": reference["torch_cuda"],
            "python": reference["python"],
            "gpu": reference["gpu"],
            "packages": {
                key: value
                for key, value in reference["packages"].items()
                if key != "llama-cpp-python"
            },
        }
        env = {
            "TRDGL_AUTO_MOUNT_DRIVE": "0",
            "TRDGL_TASK_LIMIT": "0",
            "TRDGL_MAX_TOKENS": "600",
            "TRDGL_SEED_INDEX": str(seed_index),
            "TRDGL_OUTPUT_DIR": self.remote_dir(seed),
            "TRDGL_CACHE_ROOT": self.cache_root,
        }
        source = f'''import importlib.metadata, json, os, platform
from pathlib import Path
import torch

expected = {json.dumps(expected_environment, ensure_ascii=False, sort_keys=True)!r}
expected = json.loads(expected)
env = {json.dumps(env, ensure_ascii=False, sort_keys=True)!r}
env = json.loads(env)
os.environ.update(env)
Path(env["TRDGL_OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)
Path(env["TRDGL_CACHE_ROOT"]).mkdir(parents=True, exist_ok=True)

def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"

actual = {{
    "torch_version": torch.__version__,
    "torch_cuda": torch.version.cuda,
    "python": platform.python_version(),
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "packages": {{name: package_version(name) for name in expected["packages"]}},
}}
mismatches = {{key: {{"expected": expected[key], "actual": actual[key]}}
              for key in expected if actual[key] != expected[key]}}
if mismatches:
    raise RuntimeError("TRDGL_ENV_MISMATCH " + json.dumps(mismatches, sort_keys=True))
print("TRDGL_PREFLIGHT_OK " + json.dumps({{"environment": actual, "env": env}}, sort_keys=True))
'''
        helper = seed_dir / "_remote_preflight.py"
        atomic_write_text(helper, source)
        return helper

    def run_preflight(self, seed_index: int, seed_dir: Path) -> None:
        helper = self.build_preflight(seed_index, seed_dir)
        completed = self.cli.run(
            "exec",
            "-s",
            self.args.session,
            "--timeout",
            "180",
            "-f",
            self.cli.wsl_path(helper),
            timeout=240,
        )
        if completed.returncode != 0:
            raise EvidenceContractError(
                "Colab environment does not match seed 3407; refusing to spend "
                "benchmark quota. " + summarize_error(completed.stderr, completed.stdout)
            )
        if "TRDGL_PREFLIGHT_OK" not in completed.stdout:
            raise EvidenceContractError(
                "remote preflight completed without its success marker"
            )
        self.log(f"Seed {SEEDS[seed_index]} environment contract matches seed 3407")

    def local_events(self, seed: int) -> Path:
        return self.seed_dir(seed) / "events.jsonl"

    def download_remote_events(self, seed: int) -> EventSnapshot | None:
        seed_dir = self.seed_dir(seed)
        probe = seed_dir / ".events.remote.download"
        probe.unlink(missing_ok=True)
        if not self.cli.download(
            self.remote_file(seed, "events.jsonl"), probe, timeout=180
        ):
            probe.unlink(missing_ok=True)
            return None
        try:
            remote = inspect_events(probe, seed)
        except SnapshotTransientError as exc:
            probe.unlink(missing_ok=True)
            self.log(f"Seed {seed} remote snapshot was mid-write; retry later: {exc}")
            return None
        local_path = self.local_events(seed)
        local = inspect_events(local_path, seed)
        if remote.count < local.count:
            probe.unlink(missing_ok=True)
            return local
        if remote.count == local.count and local.sha256:
            if remote.sha256 != local.sha256:
                probe.unlink(missing_ok=True)
                raise EvidenceContractError(
                    f"seed {seed} has divergent {remote.count}-row local/remote streams"
                )
            probe.unlink(missing_ok=True)
            return local
        os.replace(probe, local_path)
        return inspect_events(local_path, seed)

    def reconcile_before_run(self, seed: int) -> EventSnapshot:
        local_path = self.local_events(seed)
        local = inspect_events(local_path, seed)
        remote = self.download_remote_events(seed)
        if remote is not None and remote.count >= local.count:
            local = remote
        if local.count:
            remote_count = remote.count if remote is not None else 0
            if remote_count < local.count:
                self.log(
                    f"Uploading validated seed {seed} resume stream: "
                    f"{local.count} rows, sha256={local.sha256}"
                )
                self.cli.upload(
                    local_path, self.remote_file(seed, "events.jsonl"), timeout=300
                )
        return local

    def progress_line(
        self,
        snapshot: EventSnapshot,
        run_started: float,
        starting_count: int,
    ) -> str:
        elapsed = max(0.001, time.monotonic() - run_started)
        gained = max(0, snapshot.count - starting_count)
        rate = gained / elapsed * 3600 if gained else None
        remaining = EXPECTED_EVENTS_PER_SEED - snapshot.count
        eta = remaining / rate * 3600 if rate else None
        counts = " ".join(
            f"{baseline}={snapshot.counts[baseline]:3d}" for baseline in BASELINES
        )
        last = (
            f"{snapshot.last_baseline}:{snapshot.last_api}"
            if snapshot.last_baseline
            else "none"
        )
        rate_text = f"{rate:.1f} ev/h" if rate else "warming up"
        return (
            f"seed={snapshot.seed} {snapshot.count:3d}/{EXPECTED_EVENTS_PER_SEED} "
            f"({snapshot.count / EXPECTED_EVENTS_PER_SEED:6.2%}) | {counts} | "
            f"{rate_text} | ETA={format_duration(eta)} | last={last}"
        )

    def tee_process_output(
        self, process: subprocess.Popen[str], log_path: Path
    ) -> None:
        assert process.stdout is not None
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                handle.write(line + "\n")
                handle.flush()
                if line:
                    with self.print_lock:
                        print(f"[colab] {line}", flush=True)

    def execute_and_watch(self, seed: int) -> tuple[int, EventSnapshot]:
        seed_dir = self.seed_dir(seed)
        notebook_wsl = self.cli.wsl_path(FROZEN_NOTEBOOK)
        process = self.cli.popen(
            "exec",
            "-s",
            self.args.session,
            "--timeout",
            str(self.args.notebook_timeout_seconds),
            "-f",
            notebook_wsl,
        )
        self.current_process = process
        output_thread = threading.Thread(
            target=self.tee_process_output,
            args=(process, seed_dir / "colab_exec.log"),
            daemon=True,
        )
        output_thread.start()
        initial = inspect_events(self.local_events(seed), seed)
        last_reported = -1
        run_started = time.monotonic()
        reached_complete = False
        try:
            while process.poll() is None:
                time.sleep(self.args.poll_seconds)
                snapshot = self.download_remote_events(seed)
                if snapshot is None:
                    snapshot = inspect_events(self.local_events(seed), seed)
                if snapshot.count != last_reported:
                    self.log(self.progress_line(snapshot, run_started, initial.count))
                    self.write_state(
                        status="running",
                        current_seed=seed,
                        records=snapshot.count,
                        counts=snapshot.counts,
                        expected=EXPECTED_EVENTS_PER_SEED,
                        remaining=EXPECTED_EVENTS_PER_SEED - snapshot.count,
                        events_sha256=snapshot.sha256,
                    )
                    last_reported = snapshot.count
                if snapshot.complete and not reached_complete:
                    self.log(
                        f"Seed {seed} persisted all 480 rows; waiting for summary cell"
                    )
                    reached_complete = True
        except KeyboardInterrupt:
            process.terminate()
            raise
        finally:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
            output_thread.join(timeout=10)
            self.current_process = None
        final = self.download_remote_events(seed)
        if final is None:
            final = inspect_events(self.local_events(seed), seed)
        return process.returncode or 0, final

    def wait_for_busy_session(self, seed: int) -> EventSnapshot:
        self.log(
            f"Session is already busy; attaching to seed {seed} through validated checkpoints"
        )
        last_reported = -1
        started = time.monotonic()
        initial = inspect_events(self.local_events(seed), seed)
        while self.cli.status() == "busy":
            snapshot = self.download_remote_events(seed) or inspect_events(
                self.local_events(seed), seed
            )
            if snapshot.count != last_reported:
                self.log(self.progress_line(snapshot, started, initial.count))
                last_reported = snapshot.count
            time.sleep(self.args.poll_seconds)
        return self.download_remote_events(seed) or inspect_events(
            self.local_events(seed), seed
        )

    def download_final_artifacts(self, seed: int) -> None:
        seed_dir = self.seed_dir(seed)
        for name in (
            "run_manifest.json",
            "documentation_snapshot.json",
            "baseline_summary.csv",
            "events_compact.json",
        ):
            temporary = seed_dir / f".{name}.download"
            temporary.unlink(missing_ok=True)
            if self.cli.download(self.remote_file(seed, name), temporary, timeout=240):
                if name.endswith(".json"):
                    json.loads(temporary.read_text(encoding="utf-8"))
                os.replace(temporary, seed_dir / name)

    @staticmethod
    def _source(cell: dict[str, Any]) -> str:
        source = cell.get("source", [])
        return "".join(source) if isinstance(source, list) else str(source)

    def export_executed_notebook(self, seed: int) -> Path:
        seed_dir = self.seed_dir(seed)
        raw_log = seed_dir / "session_execution_log.ipynb"
        completed = self.cli.run(
            "log",
            "-s",
            self.args.session,
            "-t",
            "execution",
            "-o",
            self.cli.wsl_path(raw_log),
            timeout=300,
        )
        if completed.returncode != 0 or not raw_log.is_file():
            raise RunnerError(
                "could not export Colab execution log: "
                + summarize_error(completed.stderr, completed.stdout)
            )
        frozen = json.loads(FROZEN_NOTEBOOK.read_text(encoding="utf-8"))
        log_notebook = json.loads(raw_log.read_text(encoding="utf-8"))
        frozen_code = [
            cell for cell in frozen["cells"] if cell.get("cell_type") == "code"
        ]
        log_code = [
            cell
            for cell in log_notebook.get("cells", [])
            if cell.get("cell_type") == "code"
        ]
        target_sources = [self._source(cell) for cell in frozen_code]
        candidates: list[list[dict[str, Any]]] = []
        width = len(target_sources)
        for start in range(0, len(log_code) - width + 1):
            block = log_code[start : start + width]
            if [self._source(cell) for cell in block] == target_sources:
                candidates.append(block)
        if not candidates:
            raise EvidenceContractError(
                "Colab log does not contain a contiguous execution of the frozen notebook"
            )
        selected = candidates[-1]
        executed = copy.deepcopy(frozen)
        selected_iter = iter(selected)
        for cell in executed["cells"]:
            if cell.get("cell_type") != "code":
                continue
            logged = next(selected_iter)
            cell["outputs"] = copy.deepcopy(logged.get("outputs", []))
            cell["execution_count"] = logged.get("execution_count")
        output_text = json.dumps(executed, ensure_ascii=False, indent=1) + "\n"
        executed_path = seed_dir / "executed_notebook.ipynb"
        atomic_write_text(executed_path, output_text)
        contract = notebook_contract(executed_path)
        if contract["code_source_sha256"] != EXPECTED_CODE_SOURCE_SHA256:
            raise EvidenceContractError("executed notebook code differs from frozen code")
        transcript = json.dumps(executed, ensure_ascii=False)
        if "Runner finished. Events for this signature: 480 / 480" not in transcript:
            raise EvidenceContractError(
                "executed notebook lacks the 480/480 completion transcript"
            )
        return executed_path

    def validate_final(self, seed: int) -> dict[str, Any]:
        seed_dir = self.seed_dir(seed)
        events_path = self.local_events(seed)
        snapshot = inspect_events(events_path, seed)
        if not snapshot.complete:
            raise EvidenceContractError(
                f"seed {seed} is not complete: {snapshot.counts}"
            )
        if snapshot.prompt_mismatch_count:
            raise EvidenceContractError(
                f"seed {seed} has {snapshot.prompt_mismatch_count} B2/B3 prompt mismatches"
            )
        if len(snapshot.signatures) != 1:
            raise EvidenceContractError("completed shard must have exactly one signature")
        manifest_path = seed_dir / "run_manifest.json"
        executed_path = seed_dir / "executed_notebook.ipynb"
        if not manifest_path.is_file() or not executed_path.is_file():
            raise EvidenceContractError("final manifest or executed notebook is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_signature") != snapshot.signatures[0]:
            raise EvidenceContractError("event and run-manifest signatures differ")
        reference = self.frozen["reference_manifest"]
        volatile = {"created_utc", "run_signature", "event_log", "selected_task_count"}
        normalized = {key: value for key, value in manifest.items() if key not in volatile}
        reference_normalized = {
            key: value for key, value in reference.items() if key not in volatile
        }
        if normalized != reference_normalized:
            differing = sorted(
                key
                for key in set(normalized) | set(reference_normalized)
                if normalized.get(key) != reference_normalized.get(key)
            )
            raise EvidenceContractError(
                f"seed {seed} configuration differs from seed 3407: {differing}"
            )
        if manifest.get("selected_task_count") != EXPECTED_EVENTS_PER_BASELINE:
            raise EvidenceContractError("run manifest selected_task_count is not 120")
        executed_contract = notebook_contract(executed_path)
        if executed_contract["code_source_sha256"] != EXPECTED_CODE_SOURCE_SHA256:
            raise EvidenceContractError("executed notebook code hash mismatch")
        return {
            "seed": seed,
            "seed_index": SEEDS.index(seed),
            "observed_events": snapshot.count,
            "expected_events": EXPECTED_EVENTS_PER_SEED,
            "baseline_counts": snapshot.counts,
            "run_signature": snapshot.signatures[0],
            "events_sha256": snapshot.sha256,
            "prompt_mismatch_count": snapshot.prompt_mismatch_count,
            "frozen_notebook_sha256": EXPECTED_NOTEBOOK_SHA256,
            "notebook_code_source_sha256": EXPECTED_CODE_SOURCE_SHA256,
            "runner_version": EXPECTED_RUNNER_VERSION,
            "environment_equivalent_to_seed3407": True,
            "ready_as_complete_seed_shard": True,
            "ready_as_full_campaign_result": False,
            "claim_boundary": (
                "Complete one-seed shard / diagnostic checkpoint; not the final "
                "five-seed campaign result."
            ),
        }

    def build_handoff(self, seed: int, summary: dict[str, Any]) -> Path:
        seed_dir = self.seed_dir(seed)
        artifact_names = [
            "events.jsonl",
            "run_manifest.json",
            "documentation_snapshot.json",
            "baseline_summary.csv",
            "events_compact.json",
            "executed_notebook.ipynb",
        ]
        artifacts: dict[str, Any] = {}
        for name in artifact_names:
            path = seed_dir / name
            if path.is_file():
                artifacts[name] = {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
        summary = {
            "schema_version": "trdgl_seed_handoff_v1",
            "created_utc": utc_now(),
            **summary,
            "artifacts": artifacts,
        }
        summary_path = seed_dir / "handoff_summary.json"
        atomic_write_json(summary_path, summary)
        handoff_lines = [
            "TRDGL_HANDOFF_V1",
            f"seed={seed}",
            f"events={summary['observed_events']}/{summary['expected_events']}",
            "counts=" + json.dumps(summary["baseline_counts"], sort_keys=True),
            f"events_sha256={summary['events_sha256']}",
            f"run_signature={summary['run_signature']}",
            f"prompt_mismatch_count={summary['prompt_mismatch_count']}",
            f"notebook_code_source_sha256={summary['notebook_code_source_sha256']}",
            "ready_as_complete_seed_shard=true",
            "ready_as_full_campaign_result=false",
            "claim=complete seed shard / diagnostic checkpoint only",
        ]
        atomic_write_text(seed_dir / "HANDOFF.txt", "\n".join(handoff_lines) + "\n")
        bundle = seed_dir / f"trdgl_seed{seed}_handoff.zip"
        temporary = bundle.with_suffix(".zip.tmp")
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for name in artifact_names + ["handoff_summary.json", "HANDOFF.txt"]:
                path = seed_dir / name
                if path.is_file():
                    archive.write(path, arcname=name)
        os.replace(temporary, bundle)
        summary["bundle"] = {
            "path": str(bundle),
            "bytes": bundle.stat().st_size,
            "sha256": sha256_file(bundle),
        }
        atomic_write_json(summary_path, summary)
        return bundle

    def final_artifacts_present(self, seed: int) -> bool:
        seed_dir = self.seed_dir(seed)
        required = (
            "run_manifest.json",
            "executed_notebook.ipynb",
            "baseline_summary.csv",
        )
        return all((seed_dir / name).is_file() for name in required)

    def run_seed(self, seed_index: int) -> dict[str, Any]:
        seed = SEEDS[seed_index]
        seed_dir = self.seed_dir(seed)
        snapshot = inspect_events(self.local_events(seed), seed)
        self.log(
            f"Starting seed {seed} (index {seed_index}); local resume rows={snapshot.count}"
        )
        retries = 0
        while not snapshot.complete or not self.final_artifacts_present(seed):
            status = self.ensure_session()
            if status == "busy":
                snapshot = self.wait_for_busy_session(seed)
                continue
            self.configure_cache()
            self.run_preflight(seed_index, seed_dir)
            snapshot = self.reconcile_before_run(seed)
            self.log(
                f"Executing exact frozen notebook for seed {seed}; resume={snapshot.count}/480"
            )
            return_code, snapshot = self.execute_and_watch(seed)
            self.log(
                f"Notebook exited code={return_code}; seed {seed} rows={snapshot.count} "
                f"counts={snapshot.counts}"
            )
            self.download_final_artifacts(seed)
            try:
                self.export_executed_notebook(seed)
            except RunnerError as exc:
                self.log(f"Executed-notebook export pending: {exc}")
            if snapshot.complete and self.final_artifacts_present(seed):
                break
            retries += 1
            if self.args.max_execution_retries and retries >= self.args.max_execution_retries:
                raise RunnerError(
                    f"seed {seed} remains incomplete after {retries} executions"
                )
            self.log(
                f"Seed {seed} will resume after {self.args.execution_retry_seconds}s"
            )
            time.sleep(self.args.execution_retry_seconds)
        if not (seed_dir / "executed_notebook.ipynb").is_file():
            self.export_executed_notebook(seed)
        summary = self.validate_final(seed)
        bundle = self.build_handoff(seed, summary)
        self.log(
            f"SEED COMPLETE {seed}: sha256={summary['events_sha256']} "
            f"bundle={bundle}"
        )
        print("\n=== SEND THIS BLOCK OR THE ZIP TO CODEX ===", flush=True)
        print((seed_dir / "HANDOFF.txt").read_text(encoding="utf-8"), flush=True)
        print(f"ZIP={bundle}\n", flush=True)
        return summary

    def run(self) -> int:
        self.acquire_lock()
        summaries: list[dict[str, Any]] = []
        try:
            self.write_state(status="starting")
            self.log(
                "Frozen protocol verified: notebook_sha256="
                f"{EXPECTED_NOTEBOOK_SHA256}, code_sha256={EXPECTED_CODE_SOURCE_SHA256}"
            )
            for seed_index in self.args.seed_indices:
                summaries.append(self.run_seed(seed_index))
                self.write_state(
                    status="seed_complete",
                    completed_seeds=[item["seed"] for item in summaries],
                )
            self.write_state(
                status="done",
                completed_seeds=[item["seed"] for item in summaries],
                summaries=summaries,
            )
            if not self.args.keep_session:
                completed = self.cli.run(
                    "stop", "-s", self.args.session, timeout=120
                )
                self.log(
                    "Released Colab session"
                    if completed.returncode == 0
                    else "Could not release Colab session automatically"
                )
            self.log("All requested seed shards are complete")
            return 0
        except KeyboardInterrupt:
            self.write_state(status="interrupted", message="rerun the same command")
            self.log("Interrupted locally; rerun the same command to resume")
            return 130
        except Exception as exc:
            self.write_state(
                status="error",
                error_type=type(exc).__name__,
                message=str(exc),
            )
            self.log(f"FATAL {type(exc).__name__}: {exc}")
            self.log(
                f"Send {self.state_path} and {self.log_path} to Codex; raw evidence was not discarded"
            )
            return 1
        finally:
            self.release_lock()


def build_synthetic_event(
    seed: int, baseline: str, task: dict[str, Any]
) -> dict[str, Any]:
    prompt = "b2b3-prompt" if baseline in {"B2", "B3"} else baseline
    return {
        "baseline": baseline,
        **task,
        "run_signature": "a" * 64,
        "raw_output_sha256": "b" * 64,
        "raw_generation": True,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "started_utc": utc_now(),
        "finished_utc": utc_now(),
    }


def self_test() -> int:
    frozen = verify_frozen_inputs()
    reference_snapshot = inspect_events(REFERENCE_EVENTS, 3407)
    assert reference_snapshot.complete
    assert reference_snapshot.counts == {baseline: 120 for baseline in BASELINES}
    assert reference_snapshot.prompt_mismatch_count == 0
    assert parse_seed_indices("1,2,3,4") == [1, 2, 3, 4]
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "events.jsonl"
        task = next(iter(expected_tasks_for_seed(7711).values()))
        rows = [
            build_synthetic_event(7711, baseline, task) for baseline in BASELINES
        ]
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        snapshot = inspect_events(path, 7711)
        assert snapshot.count == 4
        assert snapshot.prompt_mismatch_count == 0
        mismatched = copy.deepcopy(rows)
        mismatched[-1]["prompt_sha256"] = "c" * 64
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in mismatched), encoding="utf-8"
        )
        assert inspect_events(path, 7711).prompt_mismatch_count == 1
        duplicate = rows + [rows[0]]
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in duplicate), encoding="utf-8"
        )
        try:
            inspect_events(path, 7711)
        except EvidenceContractError:
            pass
        else:
            raise AssertionError("duplicate event was not rejected")
        args = argparse.Namespace(
            output_root=Path(temporary) / "runner",
            wsl_distro="Ubuntu",
            colab_bin="colab",
            session="self-test",
            cache_mode="local",
        )
        runner = CampaignRunner(args, frozen)
        helper = runner.build_preflight(1, Path(temporary))
        compile(helper.read_text(encoding="utf-8"), str(helper), "exec")

        class FakeLogCLI:
            @staticmethod
            def wsl_path(path: Path) -> str:
                return str(path)

            @staticmethod
            def run(*command: str, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
                output_index = command.index("-o") + 1
                source = BENCHMARK_DIR / "checkpoints" / "seed3407_480" / "executed_notebook.ipynb"
                shutil.copy2(source, Path(command[output_index]))
                return subprocess.CompletedProcess(command, 0, "", "")

        runner.cli = FakeLogCLI()  # type: ignore[assignment]
        executed = runner.export_executed_notebook(7711)
        assert notebook_contract(executed)["code_source_sha256"] == EXPECTED_CODE_SOURCE_SHA256
    report = {
        "result": "pass",
        "frozen_notebook_sha256": EXPECTED_NOTEBOOK_SHA256,
        "notebook_code_source_sha256": frozen["notebook"]["code_source_sha256"],
        "runner_version": frozen["notebook"]["runner_version"],
        "reference_seed": 3407,
        "reference_events": reference_snapshot.count,
        "reference_counts": reference_snapshot.counts,
        "reference_prompt_mismatches": reference_snapshot.prompt_mismatch_count,
        "tests": [
            "frozen notebook byte/code contract",
            "reference 480-event shard",
            "seed-index parsing",
            "partial snapshot validation",
            "B2/B3 prompt mismatch detection",
            "duplicate identity rejection",
            "remote preflight helper syntax",
            "executed-notebook reconstruction",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resume the four remaining frozen TrDGL benchmark seed shards."
    )
    parser.add_argument(
        "--seed-indices",
        type=parse_seed_indices,
        default=DEFAULT_REMAINING_INDICES,
        help="Comma-separated frozen seed indices (default: 1,2,3,4).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Local checkpoint/handoff directory (default: {DEFAULT_OUTPUT_ROOT}).",
    )
    parser.add_argument("--session", default="trdgl-campaign-continuation")
    parser.add_argument("--wsl-distro", default="Ubuntu")
    parser.add_argument("--colab-bin", default="/home/fagon/.local/bin/colab")
    parser.add_argument(
        "--cache-mode",
        choices=("drive", "local"),
        default="local",
        help="Local cache reused across all seeds (default), or persistent Drive cache with local fallback.",
    )
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--assignment-retry-seconds", type=int, default=120)
    parser.add_argument("--execution-retry-seconds", type=int, default=20)
    parser.add_argument("--notebook-timeout-seconds", type=int, default=28800)
    parser.add_argument(
        "--max-execution-retries",
        type=int,
        default=0,
        help="0 means retry interrupted notebook executions without a fixed limit.",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Do not release the Colab runtime after all requested seeds finish.",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.poll_seconds < 10 or args.poll_seconds > 60:
        parser.error("--poll-seconds must be between 10 and 60")
    if args.assignment_retry_seconds < 30:
        parser.error("--assignment-retry-seconds must be at least 30")
    frozen = verify_frozen_inputs()
    if args.self_test:
        return self_test()
    if os.name != "nt":
        parser.error("this launcher currently targets Windows + WSL Colab CLI")
    runner = CampaignRunner(args, frozen)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
