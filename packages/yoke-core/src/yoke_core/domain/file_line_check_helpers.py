"""Helpers for :mod:`yoke_core.domain.file_line_check`.

Split out of the main module to keep it under the 350-line self-compliance
rule declared in the parent module docstring. Public API lives in
``file_line_check``; everything here is module-private substrate: the
dataclasses, classification constants, subprocess wrappers, rule engine,
and CLI helpers.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import subprocess
from dataclasses import dataclass
from enum import Enum

from yoke_contracts.project_contract.install_manifest import is_install_bundle_generated_path


# Git empty-tree object; used as the "old" side on initial commit (no HEAD).
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

VENDORED_PREFIXES = (
    "node_modules/",
    "vendor/",
)

LOCKFILE_BASENAMES = frozenset({
    "package-lock.json",
    "yarn.lock",
    "Cargo.lock",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
})

GENERATED_SENTINELS = frozenset({
    ".yoke/BOARD.md",
    ".yoke/BOARD.md.ts",
})

# fnmatch-style globs for generated trees that don't fit a single sentinel
# path. Rendered harness adapter files are owned by
# ``yoke_core.domain.agents_render`` (see ``runtime/harness/{harness}/agents/``);
# editing them by hand drifts from the universal source.
GENERATED_PATH_PATTERNS = (
    "runtime/harness/claude/agents/yoke-*.md",
    "runtime/harness/codex/agents/yoke-*.toml",
)

DATA_ASSET_PATHS = frozenset({
    ".yoke/board-art",
})


class Classification(str, Enum):
    AUTHORED = "authored"
    TEMPORARY_EXCEPTION = "temporary_exception"
    GENERATED = "generated"
    ARCHIVE = "archive"
    LOCKFILE = "lockfile"
    VENDORED = "vendored"
    DATA_ASSET = "data_asset"
    BINARY = "binary"
    SYMLINK = "symlink"


@dataclass
class FileEntry:
    path: str
    line_count: int
    classification: Classification


@dataclass
class ChangedFile:
    path: str
    classification: Classification
    old_line_count: int
    new_line_count: int
    delta: int


@dataclass
class CheckVerdict:
    ok: bool
    hard_fails: list[ChangedFile]
    warnings: list[ChangedFile]
    summary: str


def run_git(
    args: list[str], *, repo_root: pathlib.Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root)] + args,
        capture_output=True,
        text=True,
        errors="replace",
    )


def count_lines(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def line_count_file(abs_path: pathlib.Path) -> int:
    try:
        return count_lines(abs_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError):
        return 0


def do_classify_path(
    path: str,
    *,
    repo_root: pathlib.Path,
    temporary_exceptions: tuple[str, ...],
    archive_exceptions: tuple[str, ...],
) -> Classification:
    abs_path = repo_root / path
    try:
        if abs_path.is_symlink():
            return Classification.SYMLINK
    except OSError:
        pass

    posix_path = path.replace("\\", "/")
    # Installer-rendered files (manifest ``files``) are upstream-authored and
    # un-splittable in the receiving repo — GENERATED, not authored (14199).
    if is_install_bundle_generated_path(posix_path, repo_root):
        return Classification.GENERATED
    for pattern in temporary_exceptions:
        if fnmatch.fnmatchcase(posix_path, pattern):
            return Classification.TEMPORARY_EXCEPTION

    for pattern in archive_exceptions:
        if fnmatch.fnmatchcase(posix_path, pattern):
            return Classification.ARCHIVE

    basename = posix_path.rsplit("/", 1)[-1]
    if basename in LOCKFILE_BASENAMES or fnmatch.fnmatchcase(basename, "*.lock"):
        return Classification.LOCKFILE

    if posix_path in GENERATED_SENTINELS:
        return Classification.GENERATED

    for pattern in GENERATED_PATH_PATTERNS:
        if fnmatch.fnmatchcase(posix_path, pattern):
            return Classification.GENERATED

    if posix_path in DATA_ASSET_PATHS:
        return Classification.DATA_ASSET

    for prefix in VENDORED_PREFIXES:
        if posix_path.startswith(prefix):
            return Classification.VENDORED

    if abs_path.exists() and not abs_path.is_dir():
        try:
            abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Classification.BINARY
        except OSError:
            pass

    return Classification.AUTHORED


def git_show_line_count(
    ref: str, path: str, *, repo_root: pathlib.Path
) -> int:
    result = run_git(["show", f"{ref}:{path}"], repo_root=repo_root)
    if result.returncode != 0:
        return 0
    return count_lines(result.stdout)


def head_exists(repo_root: pathlib.Path) -> bool:
    return run_git(["rev-parse", "--verify", "HEAD"], repo_root=repo_root).returncode == 0


def collect_changed_paths(
    *, repo_root: pathlib.Path, base: str | None, staged: bool
) -> list[str]:
    if staged:
        args = ["diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    else:
        # Two-dot diff (branch vs base). Three-dot degenerates to empty when
        # base == HEAD, which silently skips all checks — never use it here.
        args = ["diff", "--name-only", "--diff-filter=ACMR", base or "main"]
    result = run_git(args, repo_root=repo_root)
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return [p.strip() for p in result.stdout.splitlines() if p.strip()]


def staged_new_count(path: str, *, repo_root: pathlib.Path) -> int:
    result = run_git(["show", f":{path}"], repo_root=repo_root)
    if result.returncode == 0:
        return count_lines(result.stdout)
    return line_count_file(repo_root / path)


def head_new_count(path: str, *, repo_root: pathlib.Path) -> int:
    return line_count_file(repo_root / path)


def classify_change(
    *,
    old: int,
    new: int,
    limit: int,
    classification: Classification,
) -> tuple[bool, bool, str]:
    """Return ``(is_hard_fail, is_warning, rule_label)``.

    Hard-fail rules only apply to AUTHORED. TEMPORARY_EXCEPTION is explicitly
    allowlisted. Everything else (archive, lockfile, vendored, data_asset,
    binary, symlink, generated) is always a PASS.
    """
    delta = new - old
    if classification == Classification.TEMPORARY_EXCEPTION:
        return (False, False, "")
    if classification != Classification.AUTHORED:
        return (False, False, "")
    if new <= limit:
        return (False, False, "")
    if old == 0:
        return (True, False, "rule 1: new authored file over limit")
    if old <= limit:
        if delta > 0:
            return (True, False, "rule 3: authored file crossed limit")
        return (False, False, "")
    if new > old:
        return (True, False, "rule 2: oversized authored file grew")
    return (False, True, "oversized-but-shrank")


def entry_to_dict(entry: FileEntry) -> dict:
    return {
        "path": entry.path,
        "line_count": entry.line_count,
        "classification": entry.classification.value,
    }


def change_to_dict(change: ChangedFile) -> dict:
    return {
        "path": change.path,
        "classification": change.classification.value,
        "old_line_count": change.old_line_count,
        "new_line_count": change.new_line_count,
        "delta": change.delta,
    }


def print_report(entries: list[FileEntry], *, limit: int, as_json: bool) -> None:
    if as_json:
        payload = {
            "limit": limit,
            "entries": [entry_to_dict(e) for e in entries],
        }
        print(json.dumps(payload, indent=2))
        return
    print(f"# file_line_check report — limit={limit} — {len(entries)} file(s)")
    print(f"{'lines':>6}  {'classification':<22}  path")
    for entry in entries:
        print(
            f"{entry.line_count:>6}  {entry.classification.value:<22}  {entry.path}"
        )


def print_verdict(verdict: CheckVerdict, *, as_json: bool) -> None:
    if as_json:
        payload = {
            "ok": verdict.ok,
            "hard_fails": [change_to_dict(c) for c in verdict.hard_fails],
            "warnings": [change_to_dict(c) for c in verdict.warnings],
            "summary": verdict.summary,
        }
        print(json.dumps(payload, indent=2))
        return
    print(f"file_line_check: {verdict.summary}")
    for change in verdict.hard_fails:
        print(
            f"  HARD-FAIL  {change.path}  "
            f"{change.old_line_count} -> {change.new_line_count} "
            f"(delta {change.delta:+d})"
        )
    for change in verdict.warnings:
        print(
            f"  WARN       {change.path}  "
            f"{change.old_line_count} -> {change.new_line_count} "
            f"(delta {change.delta:+d})"
        )
    if not verdict.ok:
        print(
            "Fix the offending file(s) or, for pre-commit only, bypass with "
            "`git commit --no-verify`."
        )


def _cli_description(limit: int) -> str:
    return (
        f"Enforce the {limit}-line authored-file limit.\n\n"
        "Subcommands:\n"
        "  report   Print per-file inventory (all tracked files).\n"
        "  check    Diff-based hard-fail check (branch-vs-base OR staged).\n\n"
        "Hard-fail rules (apply to authored files only):\n"
        f"  1. New authored file > {limit} lines.\n"
        "  2. Existing oversized authored file grows.\n"
        f"  3. Authored file crosses the {limit}-line limit upward.\n"
        "Temporary exceptions are fully exempt.\n\n"
        "Escape hatch: `git commit --no-verify` bypasses the pre-commit "
        "invocation."
    )


def build_parser(limit: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.file_line_check",
        description=_cli_description(limit),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_report = sub.add_parser(
        "report", help="print per-file inventory of tracked files"
    )
    p_report.add_argument("--json", action="store_true", help="emit JSON shape")
    p_report.add_argument("--repo", default=None, help="repo root (default: CWD)")

    p_check = sub.add_parser("check", help="diff-based hard-fail check")
    mode = p_check.add_mutually_exclusive_group()
    mode.add_argument("--base", default=None, help="branch-vs-base ref (default: main)")
    mode.add_argument(
        "--staged", action="store_true", help="staged-vs-HEAD (pre-commit)"
    )
    p_check.add_argument("--json", action="store_true", help="emit JSON shape")
    p_check.add_argument("--repo", default=None, help="repo root (default: CWD)")
    return parser
