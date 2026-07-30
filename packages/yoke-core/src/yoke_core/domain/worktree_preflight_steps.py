"""Step helpers for :mod:`yoke_core.domain.worktree_preflight`.

Sibling-extracted to keep the orchestrator + CLI under the 350-line
authored-file cap. Each helper does one thing and either reports a
boolean / pair / triple back to the orchestrator. The block-kind
string constants and the cwd-mode string constants live here too so
both modules import from one place.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from yoke_core.domain.worktree_paths import _run


# Block-kind constants surfaced on ``WorktreePreflightOutcome.block_kind``.
BLOCK_DIRTY_TRACKED = "dirty-tracked"
BLOCK_DIRTY_UNTRACKED = "dirty-untracked"
BLOCK_PATH_CLAIM = "path-claim-blocked"
BLOCK_DB_LOCK = "db-lock-substrate-contention"
BLOCK_WORK_CLAIM = "work-claim-conflict"
BLOCK_CREATE_FAILED = "worktree-create-failed"
BLOCK_INPUT = "bad-input"

# Substrate-vs-coordination classifier for activation CLI stderr.
# Lives next to BLOCK_PATH_CLAIM / BLOCK_DB_LOCK so the mapping is
# colocated with the constants. The activation CLI tags lock failures
# with the ``db-lock:`` prefix in the retry sibling
# (:mod:`advance_path_claim_activation_retry`); all other failure
# shapes are coordination/divergence — surface as path-claim blocked.
_DB_LOCK_STDERR_MARKER = "db-lock:"

# Physical-cwd modes the envelope reports back.
CWD_MODE_MATCHED = "matched"
CWD_MODE_STATIC = "static"


def resolve_item_branch_and_lane(item_id: int) -> Tuple[str, Optional[str]]:
    """Return ``(branch_name, recorded_active_lane_path)`` for an item.

    ``branch_name`` is the item's public ref (falls back to the legacy
    ``YOK-{item_id}`` form when the public sequence cannot be read).
    ``recorded_active_lane_path`` is the path of the item's active primary
    lane when one exists — so re-entry detects a worktree created under either
    the public-ref scheme or the legacy ``YOK-{internal_id}`` scheme, instead
    of reconstructing a name that may not match what is on disk.
    """
    from yoke_core.domain.worktree_naming import worktree_name_for_item

    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.item_worktrees import primary_item_worktree

        with connect() as conn:
            branch = worktree_name_for_item(conn, item_id)
            lane = primary_item_worktree(conn, int(item_id))
    except Exception:  # noqa: BLE001 - degrade if DB unavailable
        return worktree_name_for_item(None, item_id), None
    branch_out = branch
    path_out = None
    if lane:
        if lane.get("branch"):
            branch_out = str(lane["branch"])
        if lane.get("path"):
            path_out = str(lane["path"])
    return branch_out, path_out


def claim_work(item_id: int) -> Tuple[bool, str]:
    """Run ``service_client claim-work --item <item_id>``. Idempotent.

    ``item_id`` is the internal ``items.id``; it is passed bare so the
    service-client resolver maps it directly rather than treating a
    hardcoded ``YOK-`` prefix as project context (wrong for projects
    whose ``project_sequence`` diverges from ``items.id``).
    """
    r = _run([
        sys.executable,
        "-m",
        "yoke_core.api.service_client",
        "claim-work",
        "--item",
        str(item_id),
    ])
    if r.returncode == 0:
        return True, r.stdout.strip()
    return False, (r.stderr or r.stdout).strip()


def classify_activation_failure(stderr: str) -> str:
    """Return the block-kind for an activation CLI failure.

    ``BLOCK_DB_LOCK`` when the stderr carries the ``db-lock:`` marker
    emitted by the retry sibling after exhausting its backoff budget;
    ``BLOCK_PATH_CLAIM`` otherwise (the legacy default — upstream
    coordination or divergence).
    """
    if stderr and _DB_LOCK_STDERR_MARKER in stderr:
        return BLOCK_DB_LOCK
    return BLOCK_PATH_CLAIM


def extract_retry_attempts(stderr: str) -> Optional[int]:
    """Extract the retry attempt count from a ``db-lock:`` stderr line.

    Returns ``None`` when the stderr is not a db-lock failure or the
    count cannot be parsed. The retry sibling emits the literal
    ``retried N times:`` after the ``db-lock:`` prefix.
    """
    if not stderr or _DB_LOCK_STDERR_MARKER not in stderr:
        return None
    import re
    match = re.search(r"retried (\d+) times", stderr)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def activate_path_claims(item_id: int) -> Tuple[bool, str, List[int]]:
    """Run the activation phase. Returns ``(ok, stderr, activated_ids)``."""
    r = _run([
        sys.executable,
        "-m",
        "yoke_core.domain.advance_path_claim_activation",
        "--item",
        str(item_id),
    ])
    activated: List[int] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("activated="):
            try:
                parsed = json.loads(line[len("activated="):])
                if isinstance(parsed, list):
                    activated = [int(x) for x in parsed]
            except Exception:
                activated = []
    if r.returncode == 0:
        return True, "", activated
    return False, (r.stderr or r.stdout).strip(), activated


def check_dirty_main(repo_root: str) -> Tuple[bool, str, List[str]]:
    """Return ``(blocked, kind, paths)`` for tracked/staged/untracked dirt."""
    tracked = _run(["git", "-C", repo_root, "diff", "--name-only"])
    staged = _run(["git", "-C", repo_root, "diff", "--name-only", "--cached"])
    dirty_tracked = [
        p.strip()
        for p in (tracked.stdout + "\n" + staged.stdout).splitlines()
        if p.strip()
    ]
    if dirty_tracked:
        return True, BLOCK_DIRTY_TRACKED, sorted(set(dirty_tracked))
    untracked_run = _run([
        "git", "-C", repo_root, "ls-files", "--others", "--exclude-standard",
    ])
    untracked = [p.strip() for p in untracked_run.stdout.splitlines() if p.strip()]
    if untracked:
        return True, BLOCK_DIRTY_UNTRACKED, untracked
    return False, "", []


def physical_cwd_mode(actual_cwd: str, worktree_path: str) -> str:
    """``matched`` when cwd is inside ``worktree_path``; else ``static``."""
    try:
        cwd_resolved = Path(actual_cwd).resolve()
        wt_resolved = Path(worktree_path).resolve()
    except OSError:
        return CWD_MODE_STATIC
    if cwd_resolved == wt_resolved or wt_resolved in cwd_resolved.parents:
        return CWD_MODE_MATCHED
    return CWD_MODE_STATIC


__all__ = [
    "BLOCK_CREATE_FAILED",
    "BLOCK_DB_LOCK",
    "BLOCK_DIRTY_TRACKED",
    "BLOCK_DIRTY_UNTRACKED",
    "BLOCK_INPUT",
    "BLOCK_PATH_CLAIM",
    "BLOCK_WORK_CLAIM",
    "CWD_MODE_MATCHED",
    "CWD_MODE_STATIC",
    "activate_path_claims",
    "check_dirty_main",
    "claim_work",
    "classify_activation_failure",
    "extract_retry_attempts",
    "physical_cwd_mode",
    "resolve_item_branch_and_lane",
]
