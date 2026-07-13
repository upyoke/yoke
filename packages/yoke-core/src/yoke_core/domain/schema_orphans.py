"""Sibling state-directory guard helpers for yoke.db.

These functions protect against stray state-directory creation during the
yoke/ -> data/ migration window. Extracted from schema.py. Callers
import these from schema.py which re-exports them.
"""

from __future__ import annotations

from pathlib import Path


def check_sibling_state_collision(db_root: str) -> bool:
    """Return True if *db_root* is a new sibling state dir while another sibling
    already contains the live canonical ``yoke.db``.

    During the ``yoke/`` -> ``data/`` migration, the resolver on the
    rename worktree points at ``<main-root>/data`` while the shared main checkout
    still uses ``<main-root>/data/yoke.db``.  Auto-creating the new dir before
    the migration is deliberate would produce stray state.

    Returns ``True`` (collision detected, caller should abort) when:
    - The resolved *db_root* does not yet exist (nothing to clobber).
    - A sibling directory at the same repo root contains a live ``yoke.db``.

    This is the canonical policy anchor. Other state-derived
    state-derived writers (backup and ouroboros) should call
    :func:`guard_state_dir_creation` instead of reimplementing this logic.
    """
    db_root_path = Path(db_root)
    if db_root_path.exists():
        # Target already exists — not a collision, let init proceed normally.
        return False

    repo_root = db_root_path.parent
    target_name = db_root_path.name  # e.g. "data"

    # Known sibling state dirs to check (in priority order).
    sibling_names = ["yoke", "data"]
    for sibling in sibling_names:
        if sibling == target_name:
            continue
        candidate = repo_root / sibling / "yoke.db"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return True

    return False


# Keep backwards-compatible alias for internal callers.
_check_sibling_state_collision = check_sibling_state_collision


def guard_state_dir_creation(target_dir: str, caller: str) -> None:
    """Abort with a clear error if *target_dir* would create a sibling state dir.

    Intended for state-derived writers (backup, ouroboros, browser_qa)
    that derive output directories from the resolved state root and call
    ``os.makedirs(...)`` before writing.  The guard checks whether the
    **state root** (grandparent or parent of *target_dir*) would collide, not
    *target_dir* itself — the collision policy is about the top-level state dir.

    If the target directory already exists, the guard passes silently (same
    semantics as :func:`check_sibling_state_collision`).

    Raises ``RuntimeError`` with a descriptive message naming the resolved
    target and the live sibling when a collision is detected.
    """
    target_path = Path(target_dir)
    if target_path.exists():
        return

    # Walk up to find the state root (the first ancestor that is a direct child
    # of the repo root and matches a known state-dir name).
    known_state_names = {"yoke", "data"}
    candidate = target_path
    while candidate.parent != candidate:
        if candidate.name in known_state_names:
            break
        candidate = candidate.parent
    else:
        # No known state-dir ancestor — not a sibling-state scenario, allow.
        return

    if check_sibling_state_collision(str(candidate)):
        sibling_hint = "yoke/" if candidate.name == "data" else "data/"
        raise RuntimeError(
            f"Sibling-state collision detected. "
            f"Caller '{caller}' resolved target '{target_dir}' under "
            f"state dir '{candidate}' which does not exist, but a live "
            f"yoke.db was found in sibling '{sibling_hint}'. "
            f"Refusing to create directory to prevent stray state."
        )
