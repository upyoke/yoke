"""Step helpers for :mod:`yoke_core.domain.worktree_preflight`.

Sibling-extracted to keep the orchestrator + CLI under the 350-line
authored-file cap. Each helper does one thing and either reports a
boolean / pair / triple back to the orchestrator. The block-kind
string constants and the cwd-mode string constants live here too so
both modules import from one place.
"""

from __future__ import annotations

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
    """Acquire the item work claim through the connected transport.

    Routes ``claims.work.acquire`` via the transport-aware dispatcher so an
    https-connected session relays the acquisition to the control plane
    instead of opening a local Postgres connection (which refuses on an
    https transport). Idempotent: the acquire handler returns the session's
    existing claim when it already holds one.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id="claims.work.acquire",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={
            "target": {"kind": "item", "item_id": int(item_id)},
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
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
    )

    detail = call_dispatcher(
        function_id="items.detail.get",
        target=TargetRef(kind="item", item_id=int(item_id)),
    )
    if not detail.success:
        return None
    project = ((detail.result or {}).get("item") or {}).get("project") or {}
    project_id = project.get("id")
    if project_id is None:
        return None
    checkout = checkout_for_project_id(int(project_id))
    return str(checkout) if checkout is not None else None


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
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )
    from yoke_core.domain.advance_path_claim_activation_retry import (
        resolve_integration_head_with_retry,
    )

    target = TargetRef(kind="item", item_id=int(item_id))
    listed = call_dispatcher(
        function_id="claims.path.list",
        target=target,
        payload={"states": ["planned", "blocked"]},
    )
    if not listed.success:
        err = listed.error
        return False, (
            f"{err.code}: {err.message}"
            if err is not None
            else "path-claim list failed"
        ), []
    claims = (listed.result or {}).get("claims") or []

    resolved_heads: dict[int, str] = {}
    if claims:
        checkout = _local_checkout_for_item(item_id)
        if checkout is None:
            return False, (
                "claim's item has no machine-local checkout mapping; "
                "cannot resolve integration head"
            ), []
        for claim in claims:
            claim_id = int(claim["id"])
            integration_target = str(claim.get("integration_target") or "main")
            rr = resolve_integration_head_with_retry(
                None,
                project_id="",
                repo_path=checkout,
                integration_target=integration_target,
            )
            if rr.error is not None:
                # A planned claim WILL be activated; surface the resolution
                # failure (divergence / boundary / db-lock). A blocked claim
                # short-circuits server-side, so omit it and let the server
                # decide (a repair-to-planned falls back to local resolution).
                if str(claim.get("state")) == "planned":
                    return False, rr.error, []
                continue
            resolved_heads[claim_id] = str(rr.commit_sha)

    run = call_dispatcher(
        function_id="claims.path.activation_run",
        target=target,
        payload={"resolved_heads": resolved_heads},
    )
    if not run.success:
        err = run.error
        return False, (
            f"{err.code}: {err.message}"
            if err is not None
            else "path-claim activation failed"
        ), []
    result = run.result or {}
    outcomes = result.get("outcomes") or []
    activated = [
        int(o["claim_id"])
        for o in outcomes
        if o.get("state_before") == "planned" and o.get("state_after") == "active"
    ]
    diverged = result.get("diverged_error")
    blocked = list(result.get("blocked_errors") or [])
    if diverged or blocked:
        parts = ([str(diverged)] if diverged else []) + [str(b) for b in blocked]
        return False, "\n".join(parts), activated
    return True, "", activated


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
