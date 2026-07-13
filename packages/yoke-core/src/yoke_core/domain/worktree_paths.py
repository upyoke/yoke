"""Worktree path-resolution surface.

Foundation module for the worktree subsystem. Owns:

* path resolution proper — repo-root, worktree-root, project-local
  ``.yoke/`` (yoke-root), retired DB-path guard, and
  ``resolve_named_path``;
* the git-context helpers that path resolution depends on
  (``_normalize_repo_root``, ``_resolve_repo_root_from_cwd``,
  ``_strip_worktree_path``);
* the low-level primitives shared by every worktree sibling — the
  subprocess wrapper ``_run`` and the item-ID parser ``_parse_item_id``.
  Keeping these here (rather than in the front door) keeps the front
  door free of a sibling-imports-back-into-front-door cycle when
  ``python3 -m yoke_core.domain.worktree`` runs.

The front-door module re-exports every public name defined here so
``yoke_core.domain.worktree`` remains the stable API surface.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from yoke_core.domain import machine_config


# ---------------------------------------------------------------------------
# Shared low-level primitives
# ---------------------------------------------------------------------------

def _run(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a subprocess with timeout, capturing output."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")


def is_git_worktree(path: str) -> bool:
    """Return True when ``path`` is a checked-out git worktree directory."""
    if not path or not os.path.isdir(path):
        return False
    check = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    return check.returncode == 0 and check.stdout.strip() == "true"


def _parse_item_id(raw: str) -> Optional[int]:
    """Strip ``YOK-`` prefix (case-insensitive) and leading zeros, return int."""
    cleaned = re.sub(r"^[Yy][Oo][Kk]-", "", raw.strip())
    if not cleaned:
        return None
    cleaned = cleaned.lstrip("0") or "0"
    try:
        return int(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Git-context helpers
# ---------------------------------------------------------------------------

def _resolve_context_cwd() -> str:
    """Return the caller's intended cwd, not the launcher's code root."""
    return os.environ.get("YOKE_RESOLVE_CWD") or os.getcwd()


def _resolve_repo_root_from_cwd() -> Optional[str]:
    """Resolve the main repo root, handling linked worktrees."""
    return _normalize_repo_root(_resolve_context_cwd())


def _normalize_repo_root(candidate: str) -> Optional[str]:
    """Resolve *candidate* to the owning main repo root."""
    r = _run(["git", "-C", candidate, "rev-parse", "--show-toplevel"])
    if r.returncode != 0:
        return None
    repo_root = r.stdout.strip()

    git_dir_r = _run(["git", "-C", repo_root, "rev-parse", "--git-dir"])
    common_dir_r = _run(["git", "-C", repo_root, "rev-parse", "--git-common-dir"])

    if (
        git_dir_r.returncode == 0
        and common_dir_r.returncode == 0
        and git_dir_r.stdout.strip() != common_dir_r.stdout.strip()
    ):
        # Inside a linked worktree — resolve to main repo root
        common = common_dir_r.stdout.strip()
        resolved = (Path(repo_root) / common / "..").resolve()
        return str(resolved)

    return repo_root


def _resolve_root(
    cwd: Optional[str] = None,
    claude_project_dir: Optional[str] = None,
) -> Optional[str]:
    """Resolve a repo-like root from caller context.

    Resolution order:
    1. ``CLAUDE_PROJECT_DIR``
    2. ``git rev-parse --show-toplevel``

    Retired root SQLite files are deliberately not used as repo-root
    authority.
    """
    if claude_project_dir is None:
        claude_project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or None
    if cwd is None:
        cwd = _resolve_context_cwd()

    if claude_project_dir:
        return claude_project_dir

    git_root = _normalize_repo_root(cwd)
    if git_root:
        return git_root

    return None


def _strip_worktree_path(path: str) -> str:
    """Resolve a linked-worktree path back to its main repo root."""
    from yoke_core.domain import project_settings

    candidate = path.rstrip("/") or path
    # Machine-local read: worktrees_dir is a checkout layout fact, not
    # shared project policy.
    worktrees_dir = project_settings.get_project_str(
        project_settings.checkout_root(candidate), "worktrees_dir",
    )

    marker = f"/{worktrees_dir}/"
    if marker in candidate:
        return candidate.split(marker, 1)[0]
    if "/.worktrees/" in candidate:
        return candidate.split("/.worktrees/", 1)[0]
    if "/.claude/worktrees/" in candidate:
        return candidate.split("/.claude/worktrees/", 1)[0]
    return candidate


def _resolve_live_state_root(main_root: str) -> str:
    """Return the project-local Yoke contract dir for *main_root*."""
    return os.path.join(main_root, ".yoke")


def _resolve_config_path(repo_root: str) -> str:
    """Return the machine config path."""
    return str(machine_config.config_path())


# ---------------------------------------------------------------------------
# Public path-resolution API
# ---------------------------------------------------------------------------

def resolve_main_root(
    *,
    cwd: Optional[str] = None,
    claude_project_dir: Optional[str] = None,
) -> str:
    """Return the owning main repo root."""
    root = _resolve_root(cwd=cwd, claude_project_dir=claude_project_dir)
    if not root:
        raise RuntimeError(
            "Cannot resolve repo root. Not in a git repo and CLAUDE_PROJECT_DIR is not set.",
        )
    return _strip_worktree_path(root)


def resolve_worktree_root(
    *,
    cwd: Optional[str] = None,
    claude_project_dir: Optional[str] = None,
) -> str:
    """Return the active worktree root, or the main root outside worktrees."""
    if cwd is None:
        cwd = _resolve_context_cwd()
    result = _run(["git", "-C", cwd, "rev-parse", "--show-toplevel"])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    root = _resolve_root(cwd=cwd, claude_project_dir=claude_project_dir)
    if not root:
        raise RuntimeError(
            "Cannot resolve repo root. Not in a git repo and CLAUDE_PROJECT_DIR is not set.",
        )
    return root


def resolve_yoke_root(
    *,
    cwd: Optional[str] = None,
    yoke_root_env: Optional[str] = None,
    claude_project_dir: Optional[str] = None,
) -> str:
    """Return the project-local ``.yoke/`` directory."""
    if yoke_root_env is None:
        yoke_root_env = os.environ.get("YOKE_ROOT") or None

    if yoke_root_env:
        yoke_root = yoke_root_env.rstrip("/") or yoke_root_env
        candidate = Path(_strip_worktree_path(yoke_root))
        if candidate.name == ".yoke":
            return str(candidate)
        # Bare repo root — append .yoke/
        return _resolve_live_state_root(str(candidate))

    return _resolve_live_state_root(
        resolve_main_root(cwd=cwd, claude_project_dir=claude_project_dir),
    )


def resolve_db_path(
    *,
    cwd: Optional[str] = None,
    yoke_root_env: Optional[str] = None,
    claude_project_dir: Optional[str] = None,
) -> str:
    """Refuse retired local SQLite path authority."""
    yoke_root = resolve_yoke_root(
        cwd=cwd,
        yoke_root_env=yoke_root_env,
        claude_project_dir=claude_project_dir,
    )
    retired = os.path.join(yoke_root, "yoke.db")
    raise RuntimeError(
        "SQLite authority retired/guarded: Postgres authority selects "
        "the Yoke DB through YOKE_PG_DSN, not the retired root path "
        f"{retired}."
    )


def resolve_named_path(
    mode: str,
    rel_path: Optional[str] = None,
    *,
    cwd: Optional[str] = None,
    yoke_root_env: Optional[str] = None,
    claude_project_dir: Optional[str] = None,
) -> str:
    """Resolve one of the canonical path modes (``main``, ``worktree``, ``yoke``, etc.)."""
    if mode == "main":
        return resolve_main_root(cwd=cwd, claude_project_dir=claude_project_dir)
    if mode == "worktree":
        return resolve_worktree_root(cwd=cwd, claude_project_dir=claude_project_dir)
    if mode == "main-file":
        if not rel_path:
            raise ValueError("main-file requires a relative path argument")
        return os.path.join(
            resolve_main_root(cwd=cwd, claude_project_dir=claude_project_dir),
            rel_path,
        )

    yoke_root = resolve_yoke_root(
        cwd=cwd,
        yoke_root_env=yoke_root_env,
        claude_project_dir=claude_project_dir,
    )

    if mode == "yoke-root":
        return yoke_root
    if mode == "db":
        return resolve_db_path(
            cwd=cwd,
            yoke_root_env=yoke_root_env,
            claude_project_dir=claude_project_dir,
        )

    # State modes resolve via project-local .yoke/ or machine config.
    state_suffixes = {
        "config": None,
        "config-example": None,
        "board": "BOARD.md",
        "backups": "backups",
    }
    if mode in state_suffixes:
        suffix = state_suffixes[mode]
        if suffix is None:
            return str(machine_config.config_path())
        return os.path.join(yoke_root, suffix)

    # Content modes resolve via repo root (not the state dir)
    main_root = resolve_main_root(cwd=cwd, claude_project_dir=claude_project_dir)
    content_suffixes = {
        "docs": "docs",
        "epics": "epics",
        "ouroboros": "ouroboros",
        "backlog": "backlog",
    }
    if mode in content_suffixes:
        return os.path.join(main_root, content_suffixes[mode])

    raise ValueError(f"Unknown mode '{mode}'")
