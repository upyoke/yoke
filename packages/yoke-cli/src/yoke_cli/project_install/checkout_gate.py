"""Working-tree preflight and bundle-output commit for project install.

Product ``install`` / ``refresh`` refuse a dirty tree or off-default-branch
checkout before any write, then commit exactly the manifest-owned paths the
run touched. Preview and dry-run callers skip this module. Source-dev apply
still refuses a dirty tree and still commits, but does not require the
default branch — its documented target is a linked worktree.

Some manifest-owned outputs are generated local views the ignore policy
deliberately keeps out of the repository — the board render, the strategy
renders under ``.yoke/strategy/``, backups, and the install manifest itself.
Those are written to the checkout and never staged. Classification asks git
which outputs its ignore rules cover rather than naming paths here, so any
output that lands on an ignored path inherits the same treatment.
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
    """Commit manifest-owned paths this run touched.

    Outputs the ignore policy covers are generated local views: they stay on
    disk, are never staged and never force-added, and are dropped from the
    index when an older checkout still tracked them.
    """
    if skip:
        return {"status": "skipped", "reason": "no-commit"}
    if not _is_git_checkout(repo_root):
        return {"status": "skipped", "reason": "not a git checkout"}
    owned = _touched_paths(report)
    local_views = _ignored_outputs(repo_root, owned)
    untracked_from_index = _untrack_local_views(repo_root, local_views)
    views = {
        "untracked_local_outputs": sorted(local_views),
        "untracked_from_index": untracked_from_index,
    }
    dirty = {_porcelain_path(line) for line in _porcelain(repo_root)}
    to_stage = [
        path for path in owned if path in dirty and path not in local_views
    ]
    if not to_stage and not untracked_from_index:
        return {"status": "nothing_to_commit", "paths": [], **views}
    for path in to_stage:
        added = _run_git(repo_root, "add", "-A", "--", path)
        if added.returncode != 0:
            raise ProjectInstallError(
                "could not stage bundle output "
                f"{path}: {added.stderr.strip() or added.stdout.strip()}"
            )
    cached = _run_git(repo_root, "diff", "--cached", "--quiet")
    if cached.returncode == 0:
        return {"status": "nothing_to_commit", "paths": to_stage, **views}
    version = str(report.get("yoke_version") or "current bundle")
    message = _commit_message(operation, version)
    committed = _run_git(
        repo_root,
        *commit_identity_args(repo_root),
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
        **views,
    }


def _ignored_outputs(repo_root: Path, paths: list[str]) -> set[str]:
    """Return the outputs git's ignore rules cover — generated local views.

    ``--no-index`` classifies by ignore rule alone, so a view a pre-ignore
    install left tracked is still recognized as a view rather than as
    repository content.
    """
    if not paths:
        return set()
    result = _run_git_input(
        repo_root, "\0".join(paths), "check-ignore", "-z", "--no-index", "--stdin",
    )
    if result.returncode not in (0, 1):
        detail = (
            result.stderr.strip() or result.stdout.strip() or "git check-ignore failed"
        )
        raise ProjectInstallError(
            "could not classify bundle output against the ignore policy: "
            f"{detail}. rerun with --no-commit to write without committing"
        )
    return {path for path in result.stdout.split("\0") if path}


def _untrack_local_views(repo_root: Path, views: set[str]) -> list[str]:
    """Drop index entries for views the ignore policy now covers.

    A checkout onboarded before an ignore name entered the canonical set can
    still track the view. Left tracked, its rewrite is a change git refuses to
    stage, so the tree stays dirty and the next install refuses it. Untracking
    the file — never deleting it — makes the checkout match the policy.
    """
    tracked = _tracked_paths(repo_root, views)
    for path in tracked:
        removed = _run_git(repo_root, "rm", "--cached", "--quiet", "--", path)
        if removed.returncode != 0:
            detail = removed.stderr.strip() or removed.stdout.strip()
            raise ProjectInstallError(
                f"could not untrack generated local view {path}: {detail}"
            )
    return tracked


def _tracked_paths(repo_root: Path, paths: set[str]) -> list[str]:
    if not paths:
        return []
    listed = _run_git(repo_root, "ls-files", "-z", "--", *sorted(paths))
    if listed.returncode != 0:
        detail = listed.stderr.strip() or listed.stdout.strip() or "git ls-files failed"
        raise ProjectInstallError(f"could not read tracked paths: {detail}")
    return [path for path in listed.stdout.split("\0") if path]


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
    if report.get("settings_permissions_actions") or report.get(
        "settings_status_line_actions"
    ):
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


def commit_identity_args(repo_root: Path) -> list[str]:
    """Fill user.name/email only when the checkout has none."""
    args: list[str] = []
    if not _run_git(repo_root, "config", "--get", "user.email").stdout.strip():
        args.extend(["-c", "user.email=yoke-install@localhost"])
    if not _run_git(repo_root, "config", "--get", "user.name").stdout.strip():
        args.extend(["-c", "user.name=Yoke"])
    return args


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


def _run_git_input(
    repo_root: Path, stdin: str, *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


__all__ = [
    "FALLBACK_DEFAULT_BRANCH",
    "assert_ready_for_write",
    "commit_identity_args",
    "commit_touched_paths",
]
