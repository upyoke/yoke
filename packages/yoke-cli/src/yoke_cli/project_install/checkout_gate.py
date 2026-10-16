"""Preflight, commit, and verify the installer's repository outputs.

Generated ignored views stay local. Publication owns remote reconciliation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install.installed_output_paths import (
    normalized,
    discovery_commit_paths,
    owned_paths,
    manifest_owned_paths,
    managed_region_paths,
)
from yoke_contracts import terminal_detached_process

FALLBACK_DEFAULT_BRANCH = "main"
INSTALL_COMMIT_PREFIX = "Install Yoke operating layer "
REFRESH_COMMIT_PREFIX = "Refresh installed Yoke operating layer to "


def is_installer_commit_message(message: str) -> bool:
    """True when ``message`` is one this module authored.

    Publication separately proves installer territory before replacing commits.
    """
    subject = str(message or "").strip()
    return subject.startswith(INSTALL_COMMIT_PREFIX) or subject.startswith(
        REFRESH_COMMIT_PREFIX
    )


def assert_ready_for_write(
    repo_root: Path,
    *,
    default_branch: str,
    force: bool = False,
    require_default_branch: bool = True,
) -> dict[str, Any]:
    """Refuse an unsafe git checkout, or no-op when the target is not git."""
    if not is_git_checkout(repo_root):
        return {"status": "skipped", "reason": "not a git checkout"}
    dirty = porcelain(repo_root)
    branch = current_branch(repo_root)
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
    """Commit manifest-owned paths this run touched."""
    version = str(report.get("yoke_version") or "current bundle")
    manifest = files_layer.load_manifest(repo_root)
    paths = normalized(
        owned_paths(report)
        + manifest_owned_paths(manifest)
        + managed_region_paths(manifest)
    )
    if is_git_checkout(repo_root) and not skip:
        from yoke_cli.project_install.install_recovery import removed_owned_paths

        paths += removed_owned_paths(repo_root, paths)
    return commit_paths(
        repo_root, paths, message=_commit_message(operation, version), skip=skip
    )


def commit_paths(
    repo_root: Path,
    paths: list[str],
    *,
    message: str,
    skip: bool = False,
) -> dict[str, Any]:
    """Commit the given repo-relative paths under the installer identity.

    Ignored generated views stay on disk and are dropped from the index.
    """
    if skip:
        return {"status": "skipped", "reason": "no-commit"}
    if not is_git_checkout(repo_root):
        return {"status": "skipped", "reason": "not a git checkout"}
    owned = discovery_commit_paths(repo_root, normalized(paths))
    local_views = _ignored_outputs(repo_root, owned)
    untracked_from_index = _untrack_local_views(repo_root, local_views)
    views = {
        "untracked_local_outputs": sorted(local_views),
        "untracked_from_index": untracked_from_index,
    }
    dirty = {_porcelain_path(line) for line in porcelain(repo_root)}
    to_stage = [
        path
        for path in owned
        if path not in local_views
        and (path in dirty or any(changed.startswith(path + "/") for changed in dirty))
    ]
    if not to_stage and not untracked_from_index:
        return {"status": "nothing_to_commit", "paths": [], **views}
    indexed = set(_tracked_paths(repo_root, set(to_stage)))
    for path in to_stage:
        if path not in indexed and not os.path.lexists(repo_root / path):
            continue  # A previously staged deletion needs no second git add.
        added = run_git(repo_root, "add", "-A", "--", path)
        if added.returncode != 0:
            raise ProjectInstallError(
                "could not stage bundle output "
                f"{path}: {added.stderr.strip() or added.stdout.strip()}"
            )
    cached = run_git(repo_root, "diff", "--cached", "--quiet")
    if cached.returncode == 0:
        return {"status": "nothing_to_commit", "paths": to_stage, **views}
    committed = run_git(
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
    sha = run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    return {
        "status": "created",
        "sha": sha,
        "message": message,
        "paths": to_stage,
        "hooks": "skipped",
        **views,
    }


def assert_paths_committed(repo_root: Path, paths: list[str]) -> list[str]:
    """Verify all installer-written paths are committed before handoff."""
    wanted = discovery_commit_paths(repo_root, normalized(paths))
    if not wanted or not is_git_checkout(repo_root):
        return wanted
    dirty = {_porcelain_path(line) for line in porcelain(repo_root)}
    left = [
        path
        for path in wanted
        if path in dirty or any(changed.startswith(path + "/") for changed in dirty)
    ]
    if left:
        listed = "\n".join(f"  {path}" for path in left)
        raise ProjectInstallError(
            "install wrote these paths after its commit, so the checkout is "
            "dirty before you have touched it:\n"
            f"{listed}\n"
            "recipe: `git add -A && git commit` in that checkout, then "
            "report this — the install owns the commit and should not have "
            "left the write behind"
        )
    return wanted


def _ignored_outputs(repo_root: Path, paths: list[str]) -> set[str]:
    """Return the outputs git's ignore rules cover — generated local views.

    ``--no-index`` classifies by ignore rule alone, so a view a pre-ignore
    install left tracked is still recognized as a view rather than as
    repository content.
    """
    from yoke_cli.project_install.install_recovery import PENDING_REL

    if not paths:
        return {PENDING_REL}
    result = run_git_input(
        repo_root,
        "\0".join(paths),
        "check-ignore",
        "-z",
        "--no-index",
        "--stdin",
    )
    if result.returncode not in (0, 1):
        detail = (
            result.stderr.strip() or result.stdout.strip() or "git check-ignore failed"
        )
        raise ProjectInstallError(
            "could not classify bundle output against the ignore policy: "
            f"{detail}. rerun with --no-commit to write without committing"
        )
    return {PENDING_REL, *(path for path in result.stdout.split("\0") if path)}


def _untrack_local_views(repo_root: Path, views: set[str]) -> list[str]:
    """Drop index entries for views the ignore policy now covers.

    A checkout onboarded before an ignore name entered the canonical set can
    still track the view. Left tracked, its rewrite is a change git refuses to
    stage, so the tree stays dirty and the next install refuses it. Untracking
    the file — never deleting it — makes the checkout match the policy.
    """
    tracked = _tracked_paths(repo_root, views)
    for path in tracked:
        removed = run_git(repo_root, "rm", "--cached", "--quiet", "--", path)
        if removed.returncode != 0:
            detail = removed.stderr.strip() or removed.stdout.strip()
            raise ProjectInstallError(
                f"could not untrack generated local view {path}: {detail}"
            )
    return tracked


def _tracked_paths(repo_root: Path, paths: set[str]) -> list[str]:
    if not paths:
        return []
    listed = run_git(repo_root, "ls-files", "-z", "--", *sorted(paths))
    if listed.returncode != 0:
        detail = listed.stderr.strip() or listed.stdout.strip() or "git ls-files failed"
        raise ProjectInstallError(f"could not read tracked paths: {detail}")
    return [path for path in listed.stdout.split("\0") if path]


def is_git_checkout(repo_root: Path) -> bool:
    try:
        result = run_git(repo_root, "rev-parse", "--is-inside-work-tree")
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(repo_root: Path) -> str | None:
    result = run_git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        return None
    return branch


def porcelain(repo_root: Path) -> list[str]:
    result = run_git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
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


def commit_identity_args(repo_root: Path) -> list[str]:
    """Fill user.name/email only when the checkout has none."""
    args: list[str] = []
    if not run_git(repo_root, "config", "--get", "user.email").stdout.strip():
        args.extend(["-c", "user.email=yoke-install@localhost"])
    if not run_git(repo_root, "config", "--get", "user.name").stdout.strip():
        args.extend(["-c", "user.name=Yoke"])
    return args


def _commit_message(operation: str, version: str) -> str:
    if operation == "refresh":
        return f"{REFRESH_COMMIT_PREFIX}{version}"
    return f"{INSTALL_COMMIT_PREFIX}{version}"


def run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return terminal_detached_process.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def run_git_input(
    repo_root: Path, stdin: str, *args: str
) -> subprocess.CompletedProcess[str]:
    return terminal_detached_process.run(
        ["git", "-C", str(repo_root), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


__all__ = [
    "FALLBACK_DEFAULT_BRANCH",
    "INSTALL_COMMIT_PREFIX",
    "REFRESH_COMMIT_PREFIX",
    "assert_paths_committed",
    "assert_ready_for_write",
    "commit_identity_args",
    "commit_paths",
    "commit_touched_paths",
    "current_branch",
    "is_git_checkout",
    "is_installer_commit_message",
    "porcelain",
    "run_git",
]
