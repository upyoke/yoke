"""Table-backed override fact layer for path claims.

Operator-collision approval surface. Persistence is the
``path_claim_overrides`` state table; this module owns the write side
(:func:`invoke_override`, which inserts the row and emits the
``PathClaimOverride`` telemetry event in the same transaction) and the
read side that answers "is this claim pair currently overridden?".

Design contract:

* Override is **last resort.** Normal claim-collision resolution is
  documented in ``docs/path-claims.md`` (resolution tree #1-#4).
  This module's invoke surface is callers' last reach.
* Override is **pairwise.** It permits ``path_claim_id`` to proceed
  past ``blocking_claim_id`` for the named ``blocking_path_targets``.
  Other claim pairs are unaffected.
* Override **auto-retires** when either participant claim becomes
  terminal (``released`` or ``cancelled``) or when an amendment
  narrows the overridden surface out of the blocking claim's declared
  coverage.
* Override is **human-only.** Invocation is rejected when the
  ``YOKE_HOOK_EVENT`` environment variable is set. The
  rejection mirrors :func:`sessions_lifecycle_release.
  operator_override_release_claim` so the discipline is uniform.
* **State first, telemetry second.** The ``path_claim_overrides`` row
  is the durable fact the overlap classifier consumes; the
  ``PathClaimOverride`` event is emitted alongside it for audit.
* ``override_point='creation'`` requires a concrete claim row to
  already exist. The invoke entry refuses to mint a claim;
  callers register the claim first via the on-ramp, then invoke
  override against the resulting id.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


class PathClaimOverrideError(Exception):
    """Base class for path-claim override surface failures."""


class HookContextRejection(PathClaimOverrideError):
    """Override invoked from a hook context (YOKE_HOOK_EVENT set)."""


class EmptyActorReason(PathClaimOverrideError):
    """``actor_reason`` is empty or whitespace-only."""


class ClaimNotFound(PathClaimOverrideError):
    """The path_claim_id named in the override does not exist."""


def _terminal_states() -> tuple:
    return ("released", "cancelled")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _claim_exists(conn: Any, claim_id: int) -> bool:
    p = _p(conn)
    row = conn.execute(
        f"SELECT 1 FROM path_claims WHERE id = {p}",
        (int(claim_id),),
    ).fetchone()
    return row is not None


def _claim_state(conn: Any, claim_id: int) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT state FROM path_claims WHERE id = {p}",
        (int(claim_id),),
    ).fetchone()
    return None if row is None else str(row[0])


def _declared_target_ids(
    conn: Any, claim_id: int,
) -> set[int]:
    p = _p(conn)
    rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
        (int(claim_id),),
    ).fetchall()
    return {int(r[0]) for r in rows}


def invoke_override(
    conn: Any,
    *,
    path_claim_id: int,
    override_point: str,
    integration_target: str,
    actor_id: int,
    actor_reason: str,
    blocking_claim_id: Optional[int] = None,
    blocking_path_targets: Optional[Sequence[int]] = None,
    conflict_reason: Optional[str] = None,
    item_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Persist the override fact: state row first, telemetry event second.

    Validates the human-only guard (``YOKE_HOOK_EVENT``), the
    non-empty ``actor_reason``, and the claim-row existence
    requirement of ``override_point='creation'``. Inserts the
    ``path_claim_overrides`` row and emits ``PathClaimOverride`` in
    the same transaction; returns the event id.

    The row is the durable fact :func:`is_active_override` gates on.
    """
    if os.environ.get("YOKE_HOOK_EVENT"):
        raise HookContextRejection(
            "PathClaimOverride cannot be invoked from a hook context "
            f"(YOKE_HOOK_EVENT={os.environ['YOKE_HOOK_EVENT']}). "
            "This command is human-only."
        )
    if not (actor_reason or "").strip():
        raise EmptyActorReason(
            "actor_reason is required and must be non-empty; provide "
            "the operator-authored justification for this override."
        )
    if not _claim_exists(conn, path_claim_id):
        # Creation override demands a concrete claim row first.
        raise ClaimNotFound(
            f"path_claims id {path_claim_id} does not exist; register "
            "the claim before invoking override."
        )
    if blocking_claim_id is not None and not _claim_exists(
        conn, blocking_claim_id,
    ):
        raise ClaimNotFound(
            f"blocking_claim_id {blocking_claim_id} does not exist."
        )

    from yoke_core.domain.path_claims_events_override import emit_override

    targets = [int(t) for t in (blocking_path_targets or [])]
    invoked_at = iso8601_now()
    p = _p(conn)
    conn.execute(
        "INSERT INTO path_claim_overrides "
        "(path_claim_id, blocking_claim_id, blocking_path_targets, "
        " override_point, conflict_reason, integration_target, "
        " actor_id, actor_reason, item_id, project, session_id, "
        " created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, "
        f"{p}, {p})",
        (
            int(path_claim_id),
            int(blocking_claim_id) if blocking_claim_id is not None else None,
            json.dumps(targets),
            override_point,
            conflict_reason,
            integration_target,
            int(actor_id),
            actor_reason,
            item_id,
            project,
            session_id,
            invoked_at,
        ),
    )
    return emit_override(
        conn=conn,
        path_claim_id=path_claim_id,
        override_point=override_point,
        integration_target=integration_target,
        actor_id=actor_id,
        actor_reason=actor_reason,
        blocking_claim_id=blocking_claim_id,
        blocking_path_targets=targets,
        conflict_reason=conflict_reason,
        invoked_at=invoked_at,
        item_id=item_id,
        project=project,
        session_id=session_id,
    )


def list_overrides(
    conn: Any, *,
    path_claim_id: Optional[int] = None,
    blocking_claim_id: Optional[int] = None,
) -> List[dict]:
    """Return override rows from ``path_claim_overrides``.

    Filters by participant claim ids when supplied. Returns
    chronological order (oldest first); ``blocking_path_targets`` is
    decoded to a list of ints.
    """
    p = _p(conn)
    clauses: List[str] = []
    params: List[Any] = []
    if path_claim_id is not None:
        clauses.append(f"path_claim_id = {p}")
        params.append(int(path_claim_id))
    if blocking_claim_id is not None:
        clauses.append(f"blocking_claim_id = {p}")
        params.append(int(blocking_claim_id))
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    try:
        rows = conn.execute(
            "SELECT id, path_claim_id, blocking_claim_id, "
            "blocking_path_targets, override_point, conflict_reason, "
            "integration_target, actor_id, actor_reason, item_id, "
            "project, session_id, created_at "
            f"FROM path_claim_overrides {where}ORDER BY id ASC",
            tuple(params),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    out: List[dict] = []
    for row in rows:
        try:
            targets = json.loads(row[3] or "[]")
        except (TypeError, ValueError):
            targets = []
        out.append({
            "id": int(row[0]),
            "path_claim_id": int(row[1]),
            "blocking_claim_id": (
                int(row[2]) if row[2] is not None else None
            ),
            "blocking_path_targets": [int(t) for t in targets],
            "override_point": row[4],
            "conflict_reason": row[5],
            "integration_target": row[6],
            "actor_id": int(row[7]) if row[7] is not None else None,
            "actor_reason": row[8],
            "item_id": int(row[9]) if row[9] is not None else None,
            "project": row[10],
            "session_id": row[11],
            "created_at": row[12],
        })
    return out


def is_active_override(
    conn: Any,
    *,
    path_claim_id: int,
    blocking_claim_id: int,
) -> bool:
    """Is the pairwise override between the two claims currently in force?

    Retirement rules:

    * Either participant claim is in a terminal state → retired.
    * The overridden surface (named ``blocking_path_targets``) no
      longer intersects the *blocking* claim's current declared
      coverage — i.e. the holder narrowed the contention away → retired.

    The override permits ``path_claim_id`` to *eventually* claim the
    anchored paths, so the anchors are not required to be in
    ``path_claim_id``'s coverage yet — only in the blocker's. Once
    the holder narrows them out (or releases / cancels), the
    permission slip is no longer load-bearing.

    Otherwise, if at least one ``path_claim_overrides`` row names this
    pair, the override is active.
    """
    state_a = _claim_state(conn, path_claim_id)
    state_b = _claim_state(conn, blocking_claim_id)
    if state_a is None or state_b is None:
        return False
    if state_a in _terminal_states() or state_b in _terminal_states():
        return False

    overrides = list_overrides(
        conn,
        path_claim_id=path_claim_id,
        blocking_claim_id=blocking_claim_id,
    )
    if not overrides:
        return False

    declared_b = _declared_target_ids(conn, blocking_claim_id)
    for override in overrides:
        anchor_targets = set(override["blocking_path_targets"])
        if not anchor_targets:
            return True
        if anchor_targets & declared_b:
            return True
    return False


__all__ = [
    "ClaimNotFound",
    "EmptyActorReason",
    "HookContextRejection",
    "PathClaimOverrideError",
    "invoke_override",
    "is_active_override",
    "list_overrides",
]
