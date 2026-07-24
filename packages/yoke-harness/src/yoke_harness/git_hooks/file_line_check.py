"""Product-safe authored-file line-limit checker.

This is the installable-client implementation for ``yoke check file-line``
and the git pre-commit hook. It uses only git, filesystem reads, and shared
contracts; authority-bearing source-dev checks stay in ``yoke_core``.
"""

from __future__ import annotations

import fnmatch
import pathlib
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from yoke_contracts.project_contract.file_line_policy import (
    DEFAULT_LIMIT,
    default_exception_globs,
    generated_path_globs,
    resolve_file_line_policy,
    tracked_generated_views,
)
from yoke_contracts.project_contract.install_manifest import (
    is_install_bundle_generated_path,
)
from yoke_contracts.project_contract.strategy_docs_header import (
    StrategyHeaderError,
    parse_file_text,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    is_strategy_view_path,
)

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
LIMIT = DEFAULT_LIMIT

# Built-in exceptions are shared with the source-dev checker. Project-local
# additions live in .yoke/project.config and are resolved per repo_root.
TEMPORARY_EXCEPTIONS: tuple[str, ...] = default_exception_globs()
ARCHIVE_EXCEPTIONS = ("docs/archive/**",)
VENDORED_PREFIXES = ("node_modules/", "vendor/")
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
    *tracked_generated_views(),
})
GENERATED_PATH_PATTERNS = generated_path_globs()
DATA_ASSET_PATHS = frozenset({".yoke/board-art"})


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
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        errors="replace",
    )


def count_lines(text: str) -> int:
    return len(text.splitlines()) if text else 0


def line_count_file(abs_path: pathlib.Path) -> int:
    try:
        return count_lines(abs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return 0


def resolved_policy(repo_root: pathlib.Path):
    return resolve_file_line_policy(repo_root)


def _is_rendered_strategy_doc(path: str, *, repo_root: pathlib.Path) -> bool:
    if not is_strategy_view_path(path.replace("\\", "/")):
        return False
    try:
        text = (repo_root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        parse_file_text(text)
    except StrategyHeaderError:
        return False
    return True


def classify_path(path: str, *, repo_root: pathlib.Path) -> Classification:
    policy = resolved_policy(repo_root)
    return _classify_path_with_policy(path, repo_root=repo_root, policy=policy)


def _classify_path_with_policy(
    path: str, *, repo_root: pathlib.Path, policy
) -> Classification:
    if _is_rendered_strategy_doc(path, repo_root=repo_root):
        return Classification.GENERATED
    abs_path = repo_root / path
    try:
        if abs_path.is_symlink():
            return Classification.SYMLINK
    except OSError:
        pass
    posix_path = path.replace("\\", "/")
    # Installer-rendered files (manifest ``files``) are upstream-authored and
    # un-splittable in the receiving repo — classify GENERATED so a project
    # refresh commit does not hard-fail the authored-file line gate (and need
    # --no-verify) on rendered agent adapters like .claude/agents/yoke-*.md.
    if is_install_bundle_generated_path(posix_path, repo_root):
        return Classification.GENERATED
    for pattern in policy.exception_globs:
        if fnmatch.fnmatchcase(posix_path, pattern):
            return Classification.TEMPORARY_EXCEPTION
    for pattern in ARCHIVE_EXCEPTIONS:
        if fnmatch.fnmatchcase(posix_path, pattern):
            return Classification.ARCHIVE
    basename = posix_path.rsplit("/", 1)[-1]
    if basename in LOCKFILE_BASENAMES or fnmatch.fnmatchcase(basename, "*.lock"):
        return Classification.LOCKFILE
    if posix_path in GENERATED_SENTINELS:
        return Classification.GENERATED
    if any(fnmatch.fnmatchcase(posix_path, p) for p in GENERATED_PATH_PATTERNS):
        return Classification.GENERATED
    if posix_path in DATA_ASSET_PATHS:
        return Classification.DATA_ASSET
    if any(posix_path.startswith(prefix) for prefix in VENDORED_PREFIXES):
        return Classification.VENDORED
    if abs_path.exists() and not abs_path.is_dir():
        try:
            abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Classification.BINARY
        except OSError:
            pass
    return Classification.AUTHORED


def git_show_line_count(ref: str, path: str, *, repo_root: pathlib.Path) -> int:
    result = run_git(["show", f"{ref}:{path}"], repo_root=repo_root)
    return count_lines(result.stdout) if result.returncode == 0 else 0


def head_exists(repo_root: pathlib.Path) -> bool:
    return (
        run_git(["rev-parse", "--verify", "HEAD"], repo_root=repo_root).returncode
        == 0
    )


def collect_changed_paths(
    *, repo_root: pathlib.Path, base: Optional[str], staged: bool
) -> list[str]:
    args = (
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR"]
        if staged
        else ["diff", "--name-only", "--diff-filter=ACMR", base or "main"]
    )
    result = run_git(args, repo_root=repo_root)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git diff failed: {detail}")
    return [p.strip() for p in result.stdout.splitlines() if p.strip()]


def staged_new_count(path: str, *, repo_root: pathlib.Path) -> int:
    result = run_git(["show", f":{path}"], repo_root=repo_root)
    return count_lines(result.stdout) if result.returncode == 0 else line_count_file(repo_root / path)


def head_new_count(path: str, *, repo_root: pathlib.Path) -> int:
    return line_count_file(repo_root / path)


def classify_change(
    *, old: int, new: int, limit: int, classification: Classification
) -> tuple[bool, bool, str]:
    delta = new - old
    if classification != Classification.AUTHORED or new <= limit:
        return (False, False, "")
    if old == 0:
        return (True, False, "rule 1: new authored file over limit")
    if old <= limit:
        return (delta > 0, False, "rule 3: authored file crossed limit")
    if new > old:
        return (True, False, "rule 2: oversized authored file grew")
    return (False, True, "oversized-but-shrank")


def _build_changed_file(
    path: str, *, repo_root: pathlib.Path, base: Optional[str], staged: bool, policy
) -> ChangedFile:
    classification = _classify_path_with_policy(
        path, repo_root=repo_root, policy=policy
    )
    if staged:
        old_ref = "HEAD" if head_exists(repo_root) else EMPTY_TREE
        old = git_show_line_count(old_ref, path, repo_root=repo_root)
        new = staged_new_count(path, repo_root=repo_root)
    else:
        old = git_show_line_count(base or "main", path, repo_root=repo_root)
        new = head_new_count(path, repo_root=repo_root)
    return ChangedFile(path, classification, old, new, new - old)


def changed_files_check(
    *, repo_root: pathlib.Path, base: Optional[str] = None, staged: bool = False
) -> CheckVerdict:
    try:
        paths = collect_changed_paths(repo_root=repo_root, base=base, staged=staged)
    except (FileNotFoundError, RuntimeError):
        return CheckVerdict(False, [], [], "not a git working tree or base ref unknown")
    policy = resolved_policy(repo_root)
    hard_fails: list[ChangedFile] = []
    warnings: list[ChangedFile] = []
    for path in paths:
        change = _build_changed_file(
            path, repo_root=repo_root, base=base, staged=staged, policy=policy
        )
        is_hard, is_warn, _label = classify_change(
            old=change.old_line_count,
            new=change.new_line_count,
            limit=policy.limit,
            classification=change.classification,
        )
        if is_hard:
            hard_fails.append(change)
        elif is_warn:
            warnings.append(change)
    if hard_fails:
        summary = f"{len(hard_fails)} hard-fail(s), {len(warnings)} warning(s)"
    elif warnings:
        summary = f"ok with {len(warnings)} warning(s)"
    else:
        summary = f"ok: no authored file violations across {len(paths)} changed paths"
    return CheckVerdict(not hard_fails, hard_fails, warnings, summary)


def inventory(*, repo_root: pathlib.Path) -> list[FileEntry]:
    result = run_git(["ls-files"], repo_root=repo_root)
    if result.returncode != 0:
        return []
    policy = resolved_policy(repo_root)
    entries: list[FileEntry] = []
    for raw in result.stdout.splitlines():
        path = raw.strip()
        if not path:
            continue
        classification = _classify_path_with_policy(
            path, repo_root=repo_root, policy=policy
        )
        count = 0 if classification in {Classification.SYMLINK, Classification.BINARY} else line_count_file(repo_root / path)
        entries.append(FileEntry(path, count, classification))
    return sorted(entries, key=lambda e: e.path)


__all__ = [
    "ARCHIVE_EXCEPTIONS",
    "CheckVerdict",
    "ChangedFile",
    "Classification",
    "FileEntry",
    "LIMIT",
    "TEMPORARY_EXCEPTIONS",
    "changed_files_check",
    "classify_path",
    "inventory",
    "resolved_policy",
]
