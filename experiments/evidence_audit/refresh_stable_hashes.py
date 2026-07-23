"""Refresh audited hashes only after the paper source is committed and clean."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
MATRIX = HERE / "requirements_matrix.json"
PAPER = Path("TrDGL-FuzzVn_paper/main.tex")


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=WORKSPACE, check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    return completed.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_stable_paper() -> str:
    git("ls-files", "--error-unmatch", PAPER.as_posix())
    status = git("status", "--porcelain", "--", PAPER.as_posix())
    if status:
        raise SystemExit(
            "refusing to refresh evidence hashes: TrDGL-FuzzVn_paper/main.tex "
            "has uncommitted changes"
        )
    return git("rev-parse", "HEAD")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="verify stability and print prospective hashes")
    args = parser.parse_args()
    head = require_stable_paper()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    refreshed: dict[str, str] = {}
    for relative in matrix["audited_file_sha256"]:
        path = WORKSPACE / relative
        if not path.is_file():
            raise FileNotFoundError(f"audited artifact is missing: {relative}")
        refreshed[relative] = sha256(path)
    result = {
        "paper_sha256": refreshed[PAPER.as_posix()],
        "head": head,
        "audited_file_count": len(refreshed),
        "check_only": args.check_only,
    }
    if not args.check_only:
        matrix["audit_date"] = date.today().isoformat()
        matrix["working_tree_base_commit"] = head
        matrix["audited_file_sha256"] = refreshed
        temporary = MATRIX.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(MATRIX)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
