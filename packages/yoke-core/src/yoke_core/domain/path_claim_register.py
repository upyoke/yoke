"""Denial-body composition for ``path-claims register`` overlaps.

When :func:`yoke_core.domain.path_claims_register.register_for_item`
rejects a candidate because its path coverage overlaps another active
claim, the bare error string does not teach the operator what to do
next. The denial body embeds:

1. The conflicting claim id(s).
2. The overlapping repo-relative path strings.
3. The ready-to-paste
   ``yoke claims path coordination-decision-build --item YOK-N
   --conflicting-claim <id> --paths <paths>`` command that builds the
   evidence packet for the overlap.

This module owns the body string so the
:mod:`yoke_core.domain.path_claims_dispatch` ``cmd_register`` handler
stays small and the composition is unit-testable in isolation. The
``service_client_path_claims`` thin wrapper does not duplicate this
logic — it delegates to the dispatcher which delegates here.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import IncompatibleOverlap, PathClaimError
from yoke_core.domain.path_claims_read import _blocking_conflicts_for


_RESOLUTION_CMD = (
    "yoke claims path coordination-decision-build "
    "--item YOK-{item_id} --conflicting-claim {claim_id} "
    "--paths {paths}"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def compose_overlap_denial(
    *,
    item_id: int,
    integration_target: str,
    candidate_target_ids: Iterable[int],
    base_message: str,
    conn: Optional[Any] = None,
) -> str:
    """Return the multi-line denial body for an overlap rejection.

    The body opens with ``base_message`` (the underlying error text from
    :class:`yoke_core.domain.path_claims.IncompatibleOverlap`),
    enumerates each conflicting claim id with its overlapping paths,
    and emits the ``yoke claims path coordination-decision-build`` command for the
    first conflicting claim so the operator's next move is one paste.

    When ``conn`` is ``None`` or the conflict lookup yields zero rows
    (e.g. classifier said INCOMPATIBLE but the per-claim scan came back
    empty under test fixtures), the body still includes the ``item_id``
    + ``integration_target`` header and a generic resolution-command
    template with ``<paths>`` placeholder so callers see the shape.
    """
    target_ids = [int(t) for t in candidate_target_ids]
    conflicts = _resolve_conflicts(conn, integration_target, target_ids)
    lines = [
        f"BLOCKED: path-claim register overlap on item YOK-{int(item_id)} "
        f"(integration_target={integration_target!r}).",
        f"  reason: {base_message}",
    ]
    if conflicts:
        lines.append("  conflicting claims:")
        for claim_id, overlap_paths in conflicts:
            paths_str = ", ".join(overlap_paths) or "(no path strings)"
            lines.append(f"    claim {claim_id}: {paths_str}")
        first_claim_id, first_paths = conflicts[0]
        paths_arg = ",".join(first_paths) if first_paths else "<paths>"
        lines.append("")
        lines.append("Build the coordination evidence packet:")
        lines.append("  " + _RESOLUTION_CMD.format(
            item_id=int(item_id),
            claim_id=first_claim_id,
            paths=paths_arg,
        ))
    else:
        lines.append("")
        lines.append(
            "Build the coordination evidence packet (substitute the live "
            "conflicting-claim id and overlapping paths):"
        )
        lines.append("  " + _RESOLUTION_CMD.format(
            item_id=int(item_id),
            claim_id="<claim-id>",
            paths="<paths>",
        ))
    return "\n".join(lines)


def _resolve_conflicts(
    conn: Optional[Any],
    integration_target: str,
    candidate_target_ids: List[int],
) -> List[tuple[int, List[str]]]:
    """Return ``[(other_claim_id, [overlap_path_strings]), ...]``.

    Empty when no connection is available (handler may pass None for
    unit tests) or when the conflict scan finds no rows.
    """
    if conn is None or not candidate_target_ids:
        return []
    # claim_id=0 + state='planned' is the synthetic "candidate" shape
    # _blocking_conflicts_for expects when no row is in flight yet.
    try:
        rows = _blocking_conflicts_for(
            conn, 0,
            state="planned",
            integration_target=integration_target,
            target_ids=candidate_target_ids,
        )
    except db_backend.database_error_types(conn):
        return []
    out: List[tuple[int, List[str]]] = []
    for row in rows:
        other_id = int(row.get("claim_id") or 0)
        overlap_ids = row.get("blocking_target_ids") or []
        out.append((other_id, _path_strings_for(conn, overlap_ids)))
    return out


def _path_strings_for(
    conn: Any, target_ids: Iterable[int],
) -> List[str]:
    ids = [int(t) for t in (target_ids or [])]
    if not ids:
        return []
    p = _p(conn)
    placeholders = ",".join(p for _ in ids)
    try:
        rows = conn.execute(
            f"SELECT path_string FROM path_targets "
            f"WHERE id IN ({placeholders}) ORDER BY path_string",
            tuple(ids),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    return [str(r[0]) for r in rows]


def render_overlap_denial_for_register(
    conn: Any,
    *,
    exc: PathClaimError,
    item_id: int,
    integration_target: str,
    paths: Sequence[str],
    allow_planned: bool,
    session_id: Optional[str],
) -> Optional[str]:
    """Compose the denial body for a register-time overlap.

    Returns the multi-line body on overlap; returns ``None`` for any
    other ``PathClaimError`` (callers fall back to ``str(exc)``).
    Resolution-failure fallback: target-id resolution may itself raise
    (the candidate is, by definition, mid-flight); we suppress and pass
    an empty candidate list to :func:`compose_overlap_denial`, which
    still emits the header + generic command shape.
    """
    if not isinstance(exc, IncompatibleOverlap):
        return None
    try:
        from yoke_core.domain.path_claims_register import _fetch_item_project
        from yoke_core.domain.path_claims_resolve import (
            resolve_or_plan_paths_to_target_ids,
            resolve_paths_to_target_ids,
        )

        project_id = _fetch_item_project(conn, item_id)
        if allow_planned:
            target_ids = resolve_or_plan_paths_to_target_ids(
                conn, project_id, list(paths),
                item_id=item_id, session_id=session_id,
            )
        else:
            target_ids = resolve_paths_to_target_ids(
                conn, project_id, list(paths),
            )
    except Exception:
        target_ids = []
    return compose_overlap_denial(
        item_id=item_id,
        integration_target=integration_target,
        candidate_target_ids=target_ids,
        base_message=str(exc),
        conn=conn,
    )


__all__ = ["compose_overlap_denial", "render_overlap_denial_for_register"]
