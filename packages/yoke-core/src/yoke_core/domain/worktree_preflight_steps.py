"""Step helpers for :mod:`yoke_core.domain.worktree_preflight`.

Sibling-extracted to keep the orchestrator + CLI under the 350-line
authored-file cap. Each helper does one thing and either reports a
boolean / pair / triple back to the orchestrator. The block-kind
string constants and the cwd-mode string constants live here too so
both modules import from one place.
"""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

from pathlib import Path
from typing import List, Optional, Sequence, Tuple


# Block-kind constants surfaced on ``WorktreePreflightOutcome.block_kind``.
BLOCK_DIRTY_TRACKED = "dirty-tracked"
BLOCK_DIRTY_UNTRACKED = "dirty-untracked"
BLOCK_PATH_CLAIM = "path-claim-blocked"
BLOCK_DB_LOCK = "db-lock-substrate-contention"
BLOCK_WORK_CLAIM = "work-claim-conflict"
BLOCK_CREATE_FAILED = "worktree-create-failed"
BLOCK_INPUT = "bad-input"
BLOCK_UPSTREAM_STALE = "upstream-stale"
BLOCK_UPSTREAM_UNVERIFIED = "upstream-unverified"

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

    ``branch_name`` is the item's public ref.
    ``recorded_active_lane_path`` is the path of the item's active primary
    lane when one exists — so re-entry detects a worktree created under either
    the public-ref scheme or the legacy ``YOK-{internal_id}`` scheme, instead
    of reconstructing a name that may not match what is on disk. A recorded
    lane's own branch always wins, unrenamed.

    This reports a name; it does not mint one, and preflight runs that create
    no lane at all (``--no-worktree``) still need the rest of the envelope. So
    an unresolvable reference with no recorded lane yields an empty branch
    rather than a refusal — lane creation refuses at the point it would name
    something, in :func:`resolve_worktree_lanes_for_item`.
    """
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.item_worktree_resolution import ACTIVE_LANE_PRIORITY

    target = public_item_target(item_id)
    response = call_dispatcher(
        function_id="item_worktrees.list", target=target, payload={}
    )
    if not response.success:
        raise RuntimeError(
            response.error.message if response.error else "item worktree read refused"
        )
    lanes = sorted(
        [
            lane
            for lane in (response.result or {}).get("worktrees") or []
            if lane.get("state") == "active"
        ],
        key=lambda lane: (
            ACTIVE_LANE_PRIORITY.get(lane.get("lane_role"), len(ACTIVE_LANE_PRIORITY)),
            lane.get("id", 0),
        ),
    )
    lane = lanes[0] if lanes else {}
    return str(lane.get("branch") or target.public_ref), lane.get("path") or None


def claim_work(item_id: int) -> Tuple[bool, str]:
    """Acquire the item work claim through the connected transport.

    Routes ``claims.work.acquire`` via the transport-aware dispatcher so an
    https-connected session relays the acquisition to the control plane
    instead of opening a local Postgres connection (which refuses on an
    https transport). Idempotent: the acquire handler returns the session's
    existing claim when it already holds one.
    """
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id="claims.work.acquire",
        target=public_item_target(item_id),
        payload={
            "target": {"kind": "item"},
            "reason": "advance worktree preflight",
        },
    )
    if response.success:
        return True, "work claim held"
    error = response.error
    return False, (
        f"{error.code}: {error.message}"
        if error is not None
        else "work claim acquire failed"
    )


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


def _local_checkout_for_item(item_id: int) -> Optional[str]:
    """Resolve this machine's checkout path for the item's project.

    Reads the item's project id through ``items.detail.get`` (relayed
    over https, dispatched in-process on a local Postgres connection),
    then maps it to the machine-local checkout via
    ``checkout_for_project_id`` (machine config, no DB). Returns
    ``None`` when the project or its checkout mapping is unresolved.
    """
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.path_claim_activation_client import local_checkout

    return local_checkout(public_item_target(item_id), call_dispatcher)


def activate_path_claims(item_id: int) -> Tuple[bool, str, List[int]]:
    """Activate the item's planned path claims over the connected transport.

    Client-git / server-DB split so activation works over an https
    control plane, where the server has no checkout: list the item's
    non-terminal claims via ``claims.path.list``, resolve each planned
    claim's integration-target head from the machine-local checkout,
    then relay ``claims.path.activation_run`` with the resolved heads.
    The server activates using the supplied heads instead of reading a
    checkout it lacks; with no claims the map is empty and the run is a
    clean no-op in every mode. Returns ``(ok, error_text, activated_ids)``;
    ``error_text`` keeps the ``db-lock:`` marker so
    :func:`classify_activation_failure` still routes substrate contention.
    """
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.path_claim_activation_client import run_activation

    run = run_activation(
        public_item_target(item_id),
        dispatch=call_dispatcher,
        checkout_for_item=lambda: _local_checkout_for_item(item_id),
    )
    outcomes = (run.result or {}).get("outcomes") or []
    activated = [
        int(o["claim_id"])
        for o in outcomes
        if o.get("state_before") == "planned" and o.get("state_after") == "active"
    ]
    error = run.error
    return run.success, (f"{error.code}: {error.message}" if error else ""), activated


def check_dirty_main(
    repo_root: str,
    needed_paths: Sequence[str] = (),
    *,
    worktrees_dir: str = "",
    source_root_prefixes: Sequence[str] = (),
) -> Tuple[bool, str, List[str]]:
    """Return ``(blocked, kind, paths)`` for dirt that must stop creation.

    Empty *needed_paths* never blocks tracked dirt. Untracked files under
    source/package roots still block; repo-root scratch does not.
    """
    from yoke_core.domain.worktree_dirty_main_guard import overlapping_dirty_main

    blocked, kind, paths = overlapping_dirty_main(
        repo_root,
        needed_paths=needed_paths,
        worktrees_dir=worktrees_dir,
        source_root_prefixes=source_root_prefixes,
    )
    return blocked, kind, list(paths)


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
    "BLOCK_UPSTREAM_STALE",
    "BLOCK_UPSTREAM_UNVERIFIED",
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
