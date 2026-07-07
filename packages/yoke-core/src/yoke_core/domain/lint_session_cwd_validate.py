"""Per-tool-call claim-based validation for the session-cwd policy.

The session-cwd policy's authority is a session's **active work_claims**:
the session may write under any worktree it holds a claim on, under the
main control plane (the project repo root excluding ``.worktrees/``),
or under the free-path allowlist (``/tmp``, ``/var/folders/...``).

This module owns the validator surface; the slim policy glue lives in
:mod:`lint_session_cwd`. The lint reads claims directly through
:func:`session_claimed_worktrees.claimed_worktrees`.

Behaviour:

* Session with no claims → allow (no enforcement; the unconstrained
  control-plane / orchestrator session shape).
* Session with one or more claims → each target path must land under
  (a) a claimed worktree, (b) a control-plane repo root (the project's
  ``repo_path`` excluding ``.worktrees/``), or (c) a free path.
* Bash with no extractable targets → the caller passes ``fallback_cwd``
  as a synthetic target so a worktree-binding session that runs a
  control-plane read from outside its worktree still validates against
  the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.lint_session_cwd_control_plane import (
    is_under_yoke_control_plane,
)
from yoke_core.domain.lint_session_cwd_path_authority import (
    FREE_PATH_PREFIXES,
    TOOL_DIR_PREFIXES,
    derive_repo_roots as _derive_repo_roots,
    is_inside as _is_inside,
    is_inside_control_plane as _is_inside_control_plane,
    is_free_path as _path_is_free_path,
    is_under_tool_dir as _path_is_under_tool_dir,
    resolve_for_display as _resolve_for_display,
)
from yoke_core.domain.lint_session_cwd_status import (
    FAILURE_CLASS as _PRE_IMPL_FAILURE_CLASS,
    is_pre_implementing_status,
)
from yoke_core.domain.session_claimed_worktrees import (
    ClaimedWorktree,
    claimed_worktrees,
)


SCOPE_FAILURE_CLASS = "scope_mismatch"


@dataclass(frozen=True)
class ValidationVerdict:
    """Outcome of validating a tool call's targets against session authority.

    ``allow=True`` means no deny payload. ``offending_target`` and the
    surrounding context fields are populated when ``allow=False`` so the
    render layer can name the offender and the session's current
    authority. ``failure_class`` discriminates the deny reason so the
    render layer can pick the right message body and audit shape:
    ``"scope_mismatch"`` for "target not under any claim authority" and
    ``"pre_implementing_status"`` for "target is under a claimed
    worktree but the item's status is still pre-implementing".
    ``matched_claim`` and ``item_status`` are populated for the
    pre-implementing case so the emit layer can name the item directly.
    """

    allow: bool
    offending_target: str = ""
    claims: Sequence[ClaimedWorktree] = field(default_factory=tuple)
    repo_roots: Sequence[str] = field(default_factory=tuple)
    session_id: str = ""
    failure_class: str = SCOPE_FAILURE_CLASS
    matched_claim: Optional[ClaimedWorktree] = None
    item_status: Optional[str] = None


def validate_targets(
    conn: Any,
    *,
    session_id: str,
    targets: Sequence[str],
    fallback_cwd: str = "",
) -> ValidationVerdict:
    """Validate every target path against the session's claim authority.

    ``targets`` is the list of extracted target paths for the tool call.
    Empty list means "no extracted targets" — the validator falls back
    to ``fallback_cwd`` as a synthetic target so the harness cwd still
    gets checked. ``fallback_cwd`` may be empty when the caller wants
    the no-target case to allow unconditionally (Edit/Read/Write always
    carry an explicit file_path target).
    """
    if not session_id:
        return ValidationVerdict(allow=True, session_id="")

    claims = claimed_worktrees(conn, session_id=session_id)
    if not claims:
        return ValidationVerdict(allow=True, session_id=session_id)

    repo_roots = tuple(_derive_repo_roots(conn, claims))

    targets_to_check: List[str] = [
        t for t in targets if isinstance(t, str) and t.strip()
    ]
    if not targets_to_check and fallback_cwd.strip():
        targets_to_check = [fallback_cwd]

    for raw in targets_to_check:
        worktree_match = _matching_claim(raw, claims)
        if worktree_match is not None:
            # Target is inside a claimed worktree — the status gate applies
            # only to this branch. Control-plane and free-path targets stay
            # status-agnostic by design.
            status = _lookup_item_status(conn, worktree_match.item_id)
            if is_pre_implementing_status(status):
                return ValidationVerdict(
                    allow=False,
                    offending_target=_resolve_for_display(raw),
                    claims=claims,
                    repo_roots=repo_roots,
                    session_id=session_id,
                    failure_class=_PRE_IMPL_FAILURE_CLASS,
                    matched_claim=worktree_match,
                    item_status=status,
                )
            continue
        if _is_target_authorised(raw, claims=claims, repo_roots=repo_roots):
            continue
        return ValidationVerdict(
            allow=False,
            offending_target=_resolve_for_display(raw),
            claims=claims,
            repo_roots=repo_roots,
            session_id=session_id,
            failure_class=SCOPE_FAILURE_CLASS,
        )

    return ValidationVerdict(
        allow=True,
        claims=claims,
        repo_roots=repo_roots,
        session_id=session_id,
    )


def _is_target_authorised(
    target: str,
    *,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> bool:
    if _is_free_path(target):
        return True
    if _is_under_tool_dir(target):
        return True
    for claim in claims:
        if _is_inside(target, claim.worktree_path):
            return True
    for root in repo_roots:
        if _is_inside_control_plane(target, root):
            return True
    # Yoke-control-plane carve-out: any active Yoke session may
    # read its own control plane (the Yoke main repo root, excluding
    # its ``.worktrees/`` subtree) regardless of which project's
    # worktree claim it currently holds. Sibling-branch worktrees stay
    # claim-gated through ``_is_inside_control_plane``'s `.worktrees`
    # exclusion.
    if is_under_yoke_control_plane(target):
        return True
    return False


def _is_free_path(target: str) -> bool:
    return _path_is_free_path(target, prefixes=FREE_PATH_PREFIXES)


def _is_under_tool_dir(target: str) -> bool:
    return _path_is_under_tool_dir(target, prefixes=TOOL_DIR_PREFIXES)


def _matching_claim(
    target: str,
    claims: Sequence[ClaimedWorktree],
) -> Optional[ClaimedWorktree]:
    """Return the claim whose worktree contains ``target``, or ``None``.

    The lookup orders by claim insertion (matching ``claimed_worktrees``),
    so the first claim that covers the path wins. Free-path and
    control-plane targets are out of scope here — the caller checks
    them separately so the status gate fires only on the worktree
    branch.
    """
    for claim in claims:
        if _is_inside(target, claim.worktree_path):
            return claim
    return None


def _lookup_item_status(
    conn: Any, item_id: int,
) -> Optional[str]:
    """Return ``items.status`` for ``item_id`` or ``None`` on lookup miss.

    Fails open on schema mismatch (e.g. test fixtures without a
    ``status`` column) so the new status gate does not regress sessions
    whose authority comes from the existing scope check.
    """
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {p}", (int(item_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return None
    if row is None:
        return None
    try:
        value = row["status"]
    except (IndexError, KeyError, TypeError):
        value = row[0] if len(row) else None
    if isinstance(value, str):
        return value
    return None


__all__ = [
    "FREE_PATH_PREFIXES",
    "SCOPE_FAILURE_CLASS",
    "TOOL_DIR_PREFIXES",
    "ValidationVerdict",
    "validate_targets",
]
