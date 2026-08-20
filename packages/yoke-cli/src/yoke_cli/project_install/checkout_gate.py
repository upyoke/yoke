"""Working-tree preflight and bundle-output commit for project install.

Product ``install`` / ``refresh`` refuse a dirty tree or off-default-branch
checkout before any write, then commit exactly the manifest-owned paths the
run touched. Preview and dry-run callers skip this module. Source-dev apply
still refuses a dirty tree and still commits, but does not require the
default branch — its documented target is a linked worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from yoke_cli.project_install.files import MANIFEST_REL, ProjectInstallError
from yoke_contracts.cursor_permissions import CURSOR_CONFIG_RELS
from yoke_contracts.project_contract.file_line_policy import PROJECT_CONFIG_REL

FALLBACK_DEFAULT_BRANCH = "main"
_GITIGNORE_REL = ".gitignore"
_YOKE_GITIGNORE_REL = ".yoke/.gitignore"
_RETIRED_EXCEPTIONS_REL = ".yoke/file-line-exceptions"
_HOOK_SETTINGS = (
    ".claude/settings.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
)


def assert_ready_for_write(
    repo_root: Path,
    *,
    default_branch: str,
    force: bool = False,
    require_default_branch: bool = True,
) -> dict[str, Any]:
    """Refuse an unsafe git checkout, or no-op when the target is not git."""
    if not _is_git_checkout(repo_root):
        return {"status": "skipped", "reason": "not a git checkout"}
    dirty = _porcelain(repo_root)
    branch = _current_branch(repo_root)
    wanted = str(default_branch or FALLBACK_DEFAULT_BRANCH).strip() or (
        FALLBACK_DEFAULT_BRANCH
    )
    problems: list[str] = []
    if dirty:
        listed = "\n".join(f"  {line}" for line in dirty)
        problems.append(
            "working tree is dirty; commit or stash these paths before "
            "install/refresh, or pass --force:\n"
            f"{listed}\n"
            "recipe: `git add -A && git commit`  or  "
            "`git stash --include-untracked`"
        )
    if require_default_branch and branch != wanted:
        current = branch or "detached HEAD"
        problems.append(
            f"checkout is on {current!r}; project default_branch is "
            f"{wanted!r}. switch with `git switch {wanted}` or pass --force"
        )
    if problems and not force:
        raise ProjectInstallError("\n".join(problems))
    return {
        "status": "forced" if problems else "ok",
        "branch": branch,
        "default_branch": wanted,
        "dirty_paths": [_porcelain_path(line) for line in dirty],
        "forced": bool(problems),
    }


def commit_touched_paths(
    repo_root: Path,
    report: dict[str, Any],
    *,
    skip: bool = False,
    operation: str = "install",
) -> dict[str, Any]:
    """Commit manifest-owned paths this run touched. Never force-adds ignored files."""
    if skip:
        return {"status": "skipped", "reason": "no-commit"}
    if not _is_git_checkout(repo_root):
        return {"status": "skipped", "reason": "not a git checkout"}
    owned = _touched_paths(report)
    dirty = {_porcelain_path(line) for line in _porcelain(repo_root)}
    to_stage = [path for path in owned if path in dirty]
    if not to_stage:
        return {"status": "nothing_to_commit", "paths": []}
    for path in to_stage:
        added = _run_git(repo_root, "add", "-A", "--", path)
        if added.returncode != 0:
            raise ProjectInstallError(
                "could not stage bundle output "
                f"{path}: {added.stderr.strip() or added.stdout.strip()}"
            )
    cached = _run_git(repo_root, "diff", "--cached", "--quiet")
    if cached.returncode == 0:
        return {"status": "nothing_to_commit", "paths": to_stage}
    version = str(report.get("yoke_version") or "current bundle")
    message = _commit_message(operation, version)
    committed = _run_git(
        repo_root,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--no-verify",
        "-m",
        message,
    )
    if committed.returncode != 0:
        detail = committed.stderr.strip() or committed.stdout.strip()
        raise ProjectInstallError(
            "could not commit bundle output: "
            f"{detail}. set git user.name/user.email or pass --no-commit"
        )
    sha = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    return {
        "status": "created",
        "sha": sha,
        "message": message,
        "paths": to_stage,
        "hooks": "skipped",
    }


def _is_git_checkout(repo_root: Path) -> bool:
    try:
        result = _run_git(repo_root, "rev-parse", "--is-inside-work-tree")
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _current_branch(repo_root: Path) -> str | None:
    result = _run_git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        return None
    return branch


def _porcelain(repo_root: Path) -> list[str]:
    result = _run_git(
        repo_root, "status", "--porcelain", "--untracked-files=all",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git status failed"
        raise ProjectInstallError(f"could not inspect working tree: {detail}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _porcelain_path(line: str) -> str:
    rest = line[3:] if len(line) > 3 else line.strip()
    if " -> " in rest:
        rest = rest.split(" -> ", 1)[1]
    if len(rest) >= 2 and rest[0] == '"' and rest[-1] == '"':
        rest = rest[1:-1]
    return rest


def _touched_paths(report: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in (
        "files_written",
        "files_pruned",
        "contract_files_written",
        "contract_files_adopted",
        "strategy_files_written",
        "managed_markdown_written",
        "created_settings_files",
    ):
        paths.extend(_string_list(report.get(key)))
    for mapping_key in ("hooks_added", "hooks_removed"):
        mapping = report.get(mapping_key) or {}
        if isinstance(mapping, dict):
            paths.extend(str(key) for key in mapping if key)
    if report.get("gitignore_ignores_backfilled"):
        paths.append(_YOKE_GITIGNORE_REL)
    worktrees = report.get("worktrees_ignore") or {}
    if isinstance(worktrees, dict) and (
        worktrees.get("applied") or worktrees.get("status") == "written"
    ):
        paths.append(_GITIGNORE_REL)
    if report.get("settings_permissions_actions"):
        paths.append(_HOOK_SETTINGS[0])
    if report.get("cursor_permissions_actions"):
        paths.extend(CURSOR_CONFIG_RELS)
    exceptions = report.get("file_line_managed_exceptions") or {}
    if isinstance(exceptions, dict) and exceptions.get("status") == "ok":
        paths.append(PROJECT_CONFIG_REL)
    migration = report.get("file_line_config_migration") or {}
    if isinstance(migration, dict) and migration.get("status") == "ok":
        paths.append(PROJECT_CONFIG_REL)
        paths.append(_RETIRED_EXCEPTIONS_REL)
    paths.append(MANIFEST_REL)
    paths.extend(_HOOK_SETTINGS)
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        rel = str(path).replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith(".git/") or rel in seen:
            continue
        seen.add(rel)
        ordered.append(rel)
    return ordered


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _commit_message(operation: str, version: str) -> str:
    if operation == "refresh":
        return f"Refresh installed Yoke operating layer to {version}"
    return f"Install Yoke operating layer {version}"


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


__all__ = [
    "FALLBACK_DEFAULT_BRANCH",
    "assert_ready_for_write",
    "commit_touched_paths",
]
