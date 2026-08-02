"""Item-lifecycle release hook for path claims.

Sibling of :mod:`path_claims_item_hook` that owns the *release*
counterpart to its sibling's *cancel* behaviour. The canonical status-write
path runs it before commit on the same connection.

Why a sibling instead of expanding ``path_claims_item_hook.py``?
The cancel hook is small but the release path adds structural
parallelism that the spec wants surfaced as its own
module: terminal-release semantics differ from cancellation
semantics, the reason strings are distinct (``item-release`` /
``item-done`` versus ``item-cancelled`` / ``item-stopped``), and
the emitted event is :func:`emit_released` rather than
:func:`emit_cancelled`. Keeping the two hooks in their own files
also keeps each at a comfortable distance from the 350-line cap.

Behaviour:

* When the new status is ``release`` or ``done``, every non-
  non-terminal item-owned claim is *released* (not
  cancelled) with ``release_reason='item-release'`` /
  ``release_reason='item-done'``. Each release emits the
  ``PathClaimReleased`` event through
  :mod:`yoke_core.domain.path_claims_events`.
* Each successful release re-runs downstream unblock propagation so
  serial claims blocked on the released claim can move back to
  ``planned`` when no live overlap remains.
* The caller chooses the transaction boundary. Canonical status writes pass
  ``commit=False`` so item status and claim release commit together.
* ``release`` is the merge-boundary trigger: it marks merge-complete and
  is the moment item-linked work has actually landed in the
  ``integration_target``. ``done`` is a backstop so a fast-path
  done transition (or any flow that bypasses ``release``) cannot
  leave a non-terminal claim behind.
* Pinned workflow terminal ids are accepted dynamically; ``done`` has no
  privileged meaning when a version declares a different terminal stage.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, List, Optional

from yoke_core.domain import db_backend


_MERGE_BOUNDARY_STATES = ("release",)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _non_terminal_claim_ids_for_item(conn: Any, item_id: int) -> List[int]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT id FROM path_claims "
            f"WHERE owner_kind = 'item' AND owner_item_id = {p} "
            "AND state IN "
            "('planned', 'blocked', 'active')",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    return [int(r[0]) for r in rows]


def release_claims_on_item_terminal(
    conn: Any,
    *,
    item_id: int,
    new_status: str,
    terminal_statuses: Iterable[str] = (),
    propagate: bool = True,
    released_claim_ids: Optional[List[int]] = None,
    commit: bool = True,
) -> Optional[int]:
    """Release every non-terminal path claim attached to ``item_id``.

    Returns the count of claims that transitioned to ``released``
    (zero is a valid result), or ``None`` when ``new_status`` is
    not one of the terminal-release triggers (``release`` /
    ``done``).
    """
    allowed_terminal_statuses = set(terminal_statuses)
    if not allowed_terminal_statuses:
        try:
            from yoke_core.domain.workflow_runtime import (
                load_item_workflow_runtime,
            )

            allowed_terminal_statuses.update(
                load_item_workflow_runtime(
                    conn,
                    int(item_id),
                ).terminal_stage_ids
            )
        except Exception:
            pass
    if (
        new_status not in _MERGE_BOUNDARY_STATES
        and new_status not in allowed_terminal_statuses
    ):
        return None

    claim_ids = _non_terminal_claim_ids_for_item(conn, item_id)
    if not claim_ids:
        return 0

    try:
        from yoke_core.domain import path_claims_events as _events
    except ImportError:  # pragma: no cover - defensive
        _events = None  # type: ignore[assignment]
    try:
        from yoke_core.domain.path_claims import (
            IllegalTransition,
            get_claim,
            release as _release_claim,
        )
    except ImportError:  # pragma: no cover - defensive
        return 0

    try:
        from yoke_core.domain.path_claims_dependency_propagation import (
            propagate_release_unblock,
        )
    except ImportError:  # pragma: no cover - defensive
        propagate_release_unblock = None  # type: ignore[assignment]

    reason = f"item-{new_status}"
    released = 0
    for claim_id in claim_ids:
        try:
            _release_claim(
                conn,
                claim_id=claim_id,
                reason=reason,
                commit=commit,
            )
        except IllegalTransition:
            if not commit:
                raise
            continue
        released += 1
        if released_claim_ids is not None:
            released_claim_ids.append(claim_id)
        if _events is not None:
            try:
                _events.emit_released(
                    conn=conn,
                    claim=get_claim(conn, claim_id),
                    reason=reason,
                )
            except Exception:
                pass
        if propagate and propagate_release_unblock is not None:
            try:
                propagate_release_unblock(
                    conn,
                    released_claim_id=claim_id,
                    commit=commit,
                )
            except Exception:
                pass
    return released


__all__ = [
    "release_claims_on_item_terminal",
]
