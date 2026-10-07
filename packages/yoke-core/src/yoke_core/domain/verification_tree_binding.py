"""Bind verification to the session's recorded claimed source lane.

The holder-list read works over HTTPS and local authority. A free-path
checkout needs no claim lookup; a missing or mismatched lane yields a named
refusal. Public wire claims are never reconstructed as database claim rows."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.verification_tree_binding_messages import (
    ALLOW_TREE_MISMATCH_FLAG,
    ALLOW_TREE_MISMATCH_NOTICE,
    MISSING_LANE_REFUSAL_TEMPLATE,
    TREE_BINDING_REFUSAL_TEMPLATE,
    UNVERIFIED_BINDING_NOTICE,
)


@dataclass(frozen=True)
class TreeIdentity:
    """Which tree a verification run executed against."""

    root: str
    head_sha: str

    def as_payload(self) -> dict[str, str]:
        """Serialize for evidence sections and QA run records."""
        return {"root": self.root, "head_sha": self.head_sha}


def _is_inside(target: str, root: str) -> bool:
    if not target or not root:
        return False
    try:
        resolved_target = str(Path(target).resolve())
        resolved_root = str(Path(root).resolve())
    except OSError:
        return False
    if resolved_target == resolved_root:
        return True
    return resolved_target.startswith(resolved_root + os.sep)


def _tree_is_free(tree: str) -> bool:
    """True when *tree* sits under the write lint's free-path allowlist.

    Read from :mod:`yoke_core.domain.lint_session_cwd_validate` so the
    verification backstop and the write lint agree on which temp
    directories pass through unconditionally.
    """
    try:
        from yoke_core.domain.lint_session_cwd_validate import (
            FREE_PATH_PREFIXES,
        )
    except Exception:
        return False
    try:
        resolved = str(Path(tree).resolve())
    except OSError:
        return False
    for prefix in FREE_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    return False


def evaluate_tree_binding(
    tree: str,
    session_id: str,
    claim_worktrees: Sequence[str],
    *,
    surface: str,
    lane_item_id: Optional[str] = None,
) -> Optional[str]:
    """Pure decision — a remediation string, or ``None`` to proceed.

    Passes through for an empty session id, a session with no
    claim-bound worktrees (inline ``/yoke`` skill work and main-checkout
    source-dev both land here), a tree under the free-path allowlist, or
    a tree inside any claimed worktree.

    A refusal names a recovery the reader can actually run. When every
    claimed lane directory is gone, ``cd`` into the recorded path is not
    one, so that case gets its own template.
    """
    if not session_id:
        return None
    worktrees = [str(path) for path in claim_worktrees if str(path).strip()]
    if not worktrees:
        return None
    if _tree_is_free(tree):
        return None
    for worktree in worktrees:
        if _is_inside(tree, worktree):
            return None
    live = [path for path in worktrees if Path(path).is_dir()]
    if not live:
        return MISSING_LANE_REFUSAL_TEMPLATE.format(
            surface=surface,
            sid=session_id,
            wt=worktrees[0],
            tree=tree,
            item=lane_item_id if lane_item_id is not None else "<item>",
        )
    return TREE_BINDING_REFUSAL_TEMPLATE.format(
        surface=surface,
        sid=session_id,
        wt=live[0],
        tree=tree,
    )


@dataclass(frozen=True)
class ClaimLookup:
    """What the claim lookup found, and whether it could look at all.

    ``reachable=False`` distinguishes unconsulted from no claims.
    """

    worktrees: tuple[str, ...] = ()
    reachable: bool = True
    detail: str = ""
    lane_item_id: Optional[str] = None
    current_item_before_implementation: Optional[bool] = None


def resolve_claim_worktrees(session_id: str) -> ClaimLookup:
    """Worktree lanes this session holds through active work claims.

    Goes through the registered ``claims.work.holder_list`` read, so the
    answer follows the active connection: relayed to the server over
    https, dispatched in process against a local universe. A direct
    database connection would answer only on a machine that happens to
    hold the control plane locally, and silently answer "no claims"
    everywhere else.
    """
    if not session_id:
        return ClaimLookup()
    try:
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="claims.work.holder_list",
            target=TargetRef(kind="global"),
            payload={"session_id": session_id},
        )
    except Exception as exc:
        return ClaimLookup(reachable=False, detail=str(exc) or type(exc).__name__)
    if not response.success:
        message = response.error.message if response.error else "lookup refused"
        return ClaimLookup(reachable=False, detail=message)
    result = response.result or {}
    holders = result.get("holders") or []
    lanes: list[str] = []
    lane_item_id: Optional[str] = None
    for holder in holders:
        for path in holder.get("lane_worktrees") or []:
            candidate = str(path).strip()
            if candidate and candidate not in lanes:
                lanes.append(candidate)
                if lane_item_id is None:
                    scope = holder.get("scope") or {}
                    lane_item_id = scope.get("public_ref") or scope.get(
                        "epic_public_ref"
                    )
    planning = result.get("current_item_before_implementation")
    return ClaimLookup(
        worktrees=tuple(lanes),
        lane_item_id=lane_item_id,
        current_item_before_implementation=planning,
    )


def ambient_session_id() -> str:
    """The calling process's session id through the canonical chain.

    Env chain first, then the hook-written process-anchor registry. A
    bare ``YOKE_SESSION_ID`` read would miss every harness that publishes
    identity only through the registry.
    """
    try:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        return (resolve_ambient_session_id() or "").strip()
    except Exception:
        return ""


@dataclass(frozen=True)
class TreeBindingVerdict:
    """What a caller should do about this run.

    ``refusal`` stops the run; ``notice`` is printed and the run
    proceeds. They are mutually exclusive.
    """

    refusal: Optional[str] = None
    notice: Optional[str] = None


def evaluate_run(
    *,
    surface: str,
    tree: Optional[str] = None,
    allow_mismatch: bool = False,
) -> TreeBindingVerdict:
    """Resolve session and claims, then judge *tree* (default: cwd).

    One lookup serves both the refusal and the override notice, so an
    overridden run costs no more control-plane traffic than a bound one.
    """
    session_id = ambient_session_id()
    if not session_id:
        return TreeBindingVerdict()
    target = tree if tree is not None else os.getcwd()
    if _tree_is_free(target):
        # Settled without consulting anything: a free-path tree passes
        # whatever the claims say, so asking would only add a round trip
        # to every run that happens to live under a temp root.
        return TreeBindingVerdict()
    lookup = resolve_claim_worktrees(session_id)
    if not lookup.reachable:
        # Proceeding is right — an unreachable control plane must not
        # ground every test run — but it is said out loud, because the
        # whole point of this guard is that an unverified run never
        # again reads like a verified one.
        return TreeBindingVerdict(
            notice=UNVERIFIED_BINDING_NOTICE.format(
                surface=surface,
                tree=target,
                detail=lookup.detail,
            )
        )
    if not lookup.worktrees:
        return TreeBindingVerdict()
    refusal = evaluate_tree_binding(
        target,
        session_id,
        lookup.worktrees,
        surface=surface,
        lane_item_id=lookup.lane_item_id,
    )
    if refusal is None:
        return TreeBindingVerdict()
    if allow_mismatch:
        return TreeBindingVerdict(
            notice=ALLOW_TREE_MISMATCH_NOTICE.format(
                surface=surface,
                tree=target,
                wt=lookup.worktrees[0],
            )
        )
    return TreeBindingVerdict(refusal=refusal)


def _git(args: Sequence[str], cwd: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def resolve_tree_identity(start: Optional[str | Path] = None) -> Optional[TreeIdentity]:
    """Name the tree at *start* by its root and HEAD sha.

    Returns ``None`` when *start* is not inside a git worktree or has no
    commits yet — a caller recording evidence should then say so rather
    than invent an identity.
    """
    cwd = str(Path(start).resolve()) if start is not None else os.getcwd()
    if not Path(cwd).is_dir():
        return None
    root = _git(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return None
    head = _git(["rev-parse", "HEAD"], cwd)
    if head is None:
        return None
    return TreeIdentity(root=root, head_sha=head)


__all__ = [
    "ALLOW_TREE_MISMATCH_FLAG",
    "ALLOW_TREE_MISMATCH_NOTICE",
    "MISSING_LANE_REFUSAL_TEMPLATE",
    "TREE_BINDING_REFUSAL_TEMPLATE",
    "UNVERIFIED_BINDING_NOTICE",
    "ClaimLookup",
    "TreeBindingVerdict",
    "TreeIdentity",
    "ambient_session_id",
    "evaluate_run",
    "evaluate_tree_binding",
    "resolve_claim_worktrees",
    "resolve_tree_identity",
]
