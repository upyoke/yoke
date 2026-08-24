"""Lint changed Python files from the active claimed source checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class ChangedPathError(RuntimeError):
    """Raised when Git cannot resolve the changed-path set."""

    def __init__(self, returncode: int, detail: str) -> None:
        super().__init__(detail)
        self.returncode = returncode


def changed_python_paths(base: str, root: Path) -> tuple[str, ...]:
    """Return existing changed Python paths, preserving unusual filenames."""
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMRT",
            f"{base}...HEAD",
            "--",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = os.fsdecode(completed.stderr).strip()
        raise ChangedPathError(completed.returncode, detail)

    paths: list[str] = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = os.fsdecode(raw_path)
        candidate = root / relative
        if candidate.suffix == ".py" and candidate.is_file():
            paths.append(relative)
    return tuple(paths)


def _run_ruff(root: Path, arguments: Sequence[str], paths: Sequence[str]) -> int:
    completed = subprocess.run(
        ["uv", "run", "--frozen", "ruff", *arguments, "--", *paths],
        cwd=root,
        check=False,
    )
    return completed.returncode


def run(base: str, *, format_check: bool = False, root: Path | None = None) -> int:
    checkout = (root or Path.cwd()).resolve()
    try:
        paths = changed_python_paths(base, checkout)
    except ChangedPathError as exc:
        print(
            f"ruff-changed: could not compare {base!r} with HEAD",
            file=sys.stderr,
        )
        if str(exc):
            print(str(exc), file=sys.stderr)
        return exc.returncode or 1

    count = len(paths)
    if not paths:
        print(f"ruff-changed: no changed Python files against {base}; passing")
        return 0

    noun = "file" if count == 1 else "files"
    print(f"ruff-changed: checking {count} changed Python {noun} against {base}")
    check_status = _run_ruff(checkout, ("check",), paths)
    if check_status:
        print(
            f"ruff-changed: ruff check failed with status {check_status}",
            file=sys.stderr,
        )
        return check_status

    if format_check:
        format_status = _run_ruff(checkout, ("format", "--check"), paths)
        if format_status:
            print(
                f"ruff-changed: ruff format --check failed with status {format_status}",
                file=sys.stderr,
            )
            return format_status

    suffix = " and format" if format_check else ""
    print(f"ruff-changed: check{suffix} passed for {count} {noun}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev ruff-changed",
        description=(
            "Run Ruff on changed existing Python files in the current "
            "session's claimed Yoke source checkout."
        ),
    )
    parser.add_argument(
        "--base",
        required=True,
        metavar="REF",
        help="Compare the merge-base of REF and HEAD with HEAD.",
    )
    parser.add_argument(
        "--format-check",
        action="store_true",
        help="Also run `ruff format --check` on the changed files.",
    )
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return run(parsed.base, format_check=parsed.format_check)


__all__ = ["ChangedPathError", "changed_python_paths", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
