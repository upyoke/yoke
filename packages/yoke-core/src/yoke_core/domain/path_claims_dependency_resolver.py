"""Resolve item-dependency edges to path-claim ids.

Bridges :mod:`item_dependencies` (the operator-facing "ticket B waits
for ticket A" surface) and :mod:`path_claims` (the file-coverage door
lock). The CLI register dispatcher consumes this module when overlap is
detected: if every overlapping owner is covered and at least one
candidate -> blocker edge is serial, it auto-populates
``blocked_reason="path_claims.id=N"`` so the candidate lands in
``state='blocked'`` rather than rejecting outright.

The overlap classifier's coordination-aware edge-shape logic lives in
the sibling :mod:`path_claims_dependency_resolver_coordination` module.
That split keeps this at-cap file from growing and lets
``coordination_only`` edges cover overlaps without naming a path-claim
mutex upstream.

The resolver consults only ``item_dependencies`` (not
``path_claims.upstream_claim_id`` directly); ``--upstream-claim-id``
remains the advanced escape hatch for multi-claim / partial-release
coordination.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Set

from yoke_core.domain import db_backend
from yoke_core.domain.db_optional_queries import fetch_optional_rows


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _strip_sun_prefix(item_ref: str) -> str:
    """Normalize ``YOK-N`` / ``N`` into the bare integer string."""
    if not item_ref:
        return ""
    text = str(item_ref).strip()
    if text[:4].upper() == "YOK-":
        text = text[4:]
    return text.lstrip("0") or "0"


def _claim_owning_item(conn: Any, claim_id: int) -> Optional[int]:
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT item_id FROM path_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _has_dep_edge(
    conn: Any,
    *,
    dependent_item_id: int,
    blocking_item_id: int,
) -> bool:
    """Return True when ``dependent_item`` declares a non-terminal edge
    to ``blocking_item`` (one-way, callers compose for bidirectional).

    ``item_dependencies`` rows store YOK-prefixed strings; we normalize
    and match on the bare numeric form. Terminal status on the *blocking*
    item is interpreted by the satisfaction predicate elsewhere; the
    resolver itself only checks for the edge's existence. When the
    ``item_dependencies`` table does not exist (test fixtures that omit
    it, restricted projects), the resolver returns ``False`` rather than
    raising — dep-graph awareness is additive over today's behavior.
    """
    dep = str(dependent_item_id)
    blk = str(blocking_item_id)
    rows = fetch_optional_rows(
        conn,
        "SELECT dependent_item, blocking_item FROM item_dependencies",
        savepoint="_yoke_item_dependencies_probe",
    )
    for raw_dep, raw_blk in rows:
        rd = _strip_sun_prefix(raw_dep)
        rb = _strip_sun_prefix(raw_blk)
        if rd == dep and rb == blk:
            return True
    return False


def has_bidirectional_dep_edge(
    conn: Any,
    *,
    candidate_claim_id: Optional[int],
    candidate_item_id: Optional[int],
    blocking_claim_id: int,
) -> bool:
    """Bidirectional dep-graph check used by ``classify_overlap``.

    Returns True when EITHER party declares a non-terminal
    ``item_dependencies`` edge to the other's owning item. Covers the
    reverse-direction case where the blocker is downstream of the
    candidate (the upstream getting blocked from amending by their own
    downstream).

    ``candidate_item_id`` may be passed when the candidate is not yet a
    persisted claim (the register-time pre-check). Otherwise the
    candidate's owning item is resolved from ``candidate_claim_id``.
    """
    if candidate_item_id is None and candidate_claim_id is not None:
        candidate_item_id = _claim_owning_item(conn, candidate_claim_id)
    blocking_item_id = _claim_owning_item(conn, blocking_claim_id)
    if candidate_item_id is None or blocking_item_id is None:
        return False
    if candidate_item_id == blocking_item_id:
        # Same item — there is no item_dependencies edge for the
        # multi-claim case; fall through to ``False`` so the overlap
        # classifier surfaces real intra-item conflicts. Multi-claim
        # coordination still goes through the explicit
        # --upstream-claim-id flag.
        return False
    forward = _has_dep_edge(
        conn,
        dependent_item_id=candidate_item_id,
        blocking_item_id=blocking_item_id,
    )
    if forward:
        return True
    return _has_dep_edge(
        conn,
        dependent_item_id=blocking_item_id,
        blocking_item_id=candidate_item_id,
    )


def resolve_upstream_for_register(
    conn: Any,
    *,
    candidate_item_id: int,
    overlapping_claim_ids: Iterable[int],
) -> Optional[int]:
    """Pick the upstream claim id for auto-populated ``blocked_reason``.

    Returns the first overlapping claim id named by a candidate ->
    blocker serial dependency edge. Coordination-only overlaps count as
    covered (no rejection) but never become the named upstream because
    they do not hold a path-claim mutex. Partial coverage returns
    ``None`` so a legitimate missing dependency still rejects instead of
    producing a false HC warning.
    """
    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        CoordinationClassification,
        classify_inter_item_edges,
        has_forward_serial_edge,
    )

    seen: Set[int] = set()
    chosen: Optional[int] = None
    for claim_id in overlapping_claim_ids:
        if claim_id in seen:
            continue
        seen.add(claim_id)
        blocking_item_id = _claim_owning_item(conn, claim_id)
        if blocking_item_id is None:
            return None
        edge_class = classify_inter_item_edges(
            conn,
            candidate_claim_id=None,
            candidate_item_id=candidate_item_id,
            blocking_claim_id=claim_id,
        )
        if edge_class is CoordinationClassification.NO_EDGE:
            return None
        if chosen is None and has_forward_serial_edge(
            conn,
            dependent_item_id=candidate_item_id,
            blocking_item_id=blocking_item_id,
        ):
            chosen = claim_id
    return chosen


def _overlapping_claim_ids(
    conn,
    *,
    candidate_target_ids: list,
    integration_target: str,
) -> list[int]:
    from yoke_core.domain.path_claims_overlap import expand_lineage

    expanded_targets = expand_lineage(conn, candidate_target_ids)
    if not expanded_targets:
        return []
    p = _placeholder(conn)
    placeholders = ",".join(p for _ in expanded_targets)
    rows = conn.execute(
        f"SELECT DISTINCT pct.claim_id FROM path_claim_targets pct "
        f"JOIN path_claims pc ON pc.id = pct.claim_id "
        f"WHERE pc.integration_target = {p} "
        f"AND pc.state IN ('planned', 'blocked', 'active') "
        f"AND pc.mode <> 'exception' "
        f"AND pct.target_id IN ({placeholders}) "
        f"ORDER BY pct.claim_id",
        (integration_target, *expanded_targets),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _candidate_target_ids(
    conn: Any,
    *,
    item_id: int,
    paths: Iterable[str],
    directory_paths: Optional[Iterable[str]],
    tentative_paths: Optional[Iterable[str]],
    allow_planned: bool,
) -> list:
    """Resolve candidate paths to target ids using the same resolver
    register would invoke. Returns an empty list on resolver failure
    (the register call below will surface the real error).
    """
    try:
        p = _placeholder(conn)
        if allow_planned:
            from yoke_core.domain.path_claims_resolve import (
                resolve_or_plan_paths_to_target_ids,
            )
            project_row = conn.execute(
                f"SELECT project_id FROM items WHERE id = {p}", (item_id,),
            ).fetchone()
            project_id = (
                int(project_row[0]) if project_row and project_row[0]
                else None
            )
            return resolve_or_plan_paths_to_target_ids(
                conn,
                project_id,
                list(paths),
                item_id=item_id,
                directory_paths=(
                    list(directory_paths) if directory_paths else None
                ),
                tentative_paths=(
                    list(tentative_paths) if tentative_paths else None
                ),
            )
        from yoke_core.domain.path_claims_register import (
            resolve_paths_to_target_ids,
        )
        project_row = conn.execute(
            f"SELECT project_id FROM items WHERE id = {p}", (item_id,),
        ).fetchone()
        project_id = (
            int(project_row[0]) if project_row and project_row[0]
            else None
        )
        return resolve_paths_to_target_ids(
            conn, project_id, list(paths),
        )
    except Exception:  # noqa: BLE001
        return []


def auto_resolve_upstream(
    conn: Any,
    *,
    item_id: int,
    integration_target: str,
    paths: Iterable[str],
    directory_paths: Optional[Iterable[str]] = None,
    tentative_paths: Optional[Iterable[str]] = None,
    allow_planned: bool = False,
) -> Optional[int]:
    """Find the upstream claim id implied by ``item_dependencies``.

    Pre-register helper: probe overlapping claims on the
    candidate's ``integration_target`` and return the first one whose
    owning item is the named blocker on a non-terminal
    ``item_dependencies`` edge from the candidate. Returns ``None``
    when no such claim exists (caller falls back to the existing
    overlap-rejection path; explicit ``--upstream-claim-id`` is also
    untouched).
    """
    candidate_targets = _candidate_target_ids(
        conn,
        item_id=item_id,
        paths=paths,
        directory_paths=directory_paths,
        tentative_paths=tentative_paths,
        allow_planned=allow_planned,
    )
    if not candidate_targets:
        return None
    candidate_overlaps = _overlapping_claim_ids(
        conn,
        candidate_target_ids=candidate_targets,
        integration_target=integration_target,
    )
    if not candidate_overlaps:
        return None
    return resolve_upstream_for_register(
        conn,
        candidate_item_id=item_id,
        overlapping_claim_ids=candidate_overlaps,
    )


def cross_check_explicit_upstream(
    conn: Any,
    *,
    item_id: int,
    upstream_claim_id: int,
) -> Optional[str]:
    """Compare an operator-supplied ``--upstream-claim-id`` to the
    dep-graph. Returns an advisory message when the explicit upstream
    does not match the dep-graph, or ``None`` when they agree (or no
    edge exists to cross-check).
    """
    upstream_item = _claim_owning_item(conn, upstream_claim_id)
    if upstream_item is None:
        return None
    if _has_dep_edge(
        conn,
        dependent_item_id=item_id,
        blocking_item_id=upstream_item,
    ):
        return None
    if _has_dep_edge(
        conn,
        dependent_item_id=upstream_item,
        blocking_item_id=item_id,
    ):
        return None
    return (
        f"Advisory: --upstream-claim-id {upstream_claim_id} (item "
        f"YOK-{upstream_item}) has no item_dependencies edge from/to "
        f"YOK-{item_id}. Honoring explicit upstream."
    )


__all__ = [
    "auto_resolve_upstream",
    "cross_check_explicit_upstream",
    "has_bidirectional_dep_edge",
    "resolve_upstream_for_register",
]
