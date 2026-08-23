"""Overlap classification for path-claim registration and activation.

Given a candidate target set on an integration target, decide whether it
conflicts with any non-terminal claim already on that target.

The classifier is intentionally narrow:

* ``NONE`` — the candidate's targets are disjoint from every other
  non-terminal claim on the same integration target.
* ``SERIAL_VIA_DEPENDENCY`` — the candidate overlaps a non-terminal
  claim, but the operator declared a serial-blocker dependency
  (``upstream_claim_id``) and the upstream claim's lineage names a
  consumer/producer ordering. The caller stores the candidate as
  ``blocked`` and waits for the upstream to ``release``.
* ``INCOMPATIBLE`` — the candidate overlaps an active claim on the
  same integration target with no dependency edge. Registering or
  activating in this state would create the double-claim failure mode
  the door lock exists to prevent.

The classifier does not look at git history, snapshot contents, or
content semantics. It compares ``path_claim_targets.target_id``
membership only. Snapshot-based verification is out of scope here.

* Cross-target classification (claim on ``main`` vs claim on
  ``release/2026.01``) returns ``NONE`` — different integration
  targets are independent door locks by definition.
* Frozen item-owned claims are dormant: register, widen, and
  activation checks skip them so parked coordination cannot block
  live work. Thaw revalidates before that authority returns.
Recorded conflict surveys are advisory declarations rather than door
locks, so they are intentionally outside this classifier.
"""

from __future__ import annotations

import enum
from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_lineage import expand_lineage
from yoke_core.domain.path_render_overlap import (
    is_render_target_only_overlap as render_target_only_overlap,
)
from yoke_core.domain.schema_common import _column_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class OverlapClassification(enum.Enum):
    """Result of :func:`classify_overlap` against the candidate target set."""

    NONE = "none"
    SERIAL_VIA_DEPENDENCY = "serial_via_dependency"
    INCOMPATIBLE = "incompatible"


_NON_TERMINAL_STATES = ("planned", "blocked", "active")
_ACTIVATION_CONFLICT_STATES = ("active",)


def _target_paths(
    conn: Any,
    *,
    target_ids: Sequence[int],
) -> tuple[Optional[int | str], tuple[str, ...], dict[str, int]]:
    unique_ids = tuple(dict.fromkeys(int(value) for value in target_ids))
    if not unique_ids:
        return None, (), {}
    placeholders = ",".join(_p(conn) for _ in unique_ids)
    rows = conn.execute(
        f"SELECT id, project_id, path_string FROM path_targets "
        f"WHERE id IN ({placeholders})",
        unique_ids,
    ).fetchall()
    project_ids = {row[1] for row in rows}
    if len(rows) != len(unique_ids) or len(project_ids) != 1:
        return None, (), {}
    paths = tuple(str(row[2]) for row in rows)
    target_ids_by_path = {str(row[2]): int(row[0]) for row in rows}
    return project_ids.pop(), paths, target_ids_by_path


def _is_render_target_only_overlap(
    conn: Any,
    *,
    candidate_target_ids: Sequence[int],
    other_claim_id: int,
) -> bool:
    """Adapt claim target ids to the shared render-overlap rule."""
    project_id, candidate_paths, candidate_target_ids_by_path = _target_paths(
        conn,
        target_ids=candidate_target_ids,
    )
    if project_id is None:
        return False
    rows = conn.execute(
        "SELECT pt.path_string FROM path_claim_targets pct "
        "JOIN path_targets pt ON pt.id=pct.target_id "
        f"WHERE pct.claim_id={_p(conn)} AND pt.project_id={_p(conn)}",
        (other_claim_id, project_id),
    ).fetchall()
    return render_target_only_overlap(
        conn,
        candidate_paths=candidate_paths,
        other_paths=[str(row[0]) for row in rows],
        project_id=project_id,
        target_ids_by_path=candidate_target_ids_by_path,
    )


def _candidate_intersects(
    conn: Any,
    *,
    candidate_target_ids: Sequence[int],
    other_claim_id: int,
) -> bool:
    placeholders = ",".join(_p(conn) for _ in candidate_target_ids)
    row = conn.execute(
        f"SELECT 1 FROM path_claim_targets "
        f"WHERE claim_id = {_p(conn)} AND target_id IN ({placeholders}) LIMIT 1",
        (other_claim_id, *candidate_target_ids),
    ).fetchone()
    return row is not None


def classify_overlap(
    conn: Any,
    *,
    target_ids: Sequence[int],
    integration_target: str,
    upstream_claim_id: Optional[int] = None,
    exclude_claim_id: Optional[int] = None,
    phase: str = "register",
    candidate_item_id: Optional[int] = None,
) -> OverlapClassification:
    """Classify the candidate target set against the same-target frontier.

    Two ``phase`` modes:

    * ``"register"`` — checks every non-terminal claim
      (``planned``/``blocked``/``active``). The candidate must not
      race against another not-yet-active claim on the same surface
      unless the operator has named a serial-via-dependency upstream.
    * ``"activate"`` — checks only ``active`` claims (an
      incompatible active claim blocks activation). A planned or
      blocked sibling does not hold the door lock and therefore
      cannot conflict at activation time. The serial-via-dep
      shortcut still applies because activate paths may pass an
      ``upstream_claim_id`` to indicate "I am the downstream of
      this lineage."

    Directional dep-graph awareness:

    * **Candidate-as-DEPENDENT.** Even without an explicit
      ``--upstream-claim-id``, if the candidate's owning item is the
      DEPENDENT party of a non-coordination ``item_dependencies`` edge
      to the other claim's owning item, the pair is classified as
      ``SERIAL_VIA_DEPENDENCY``. ``widen`` callers (``phase='register'``)
      inherit the same posture so a claim that registered with a dep
      edge does not lose serial classification when amending coverage.
    * **Candidate-as-BLOCKER (upstream-of-``blocks``).** When the only
      linking non-coordination edges have the candidate as the BLOCKER
      and the other party as the DEPENDENT, the candidate is upstream
      and does not wait. The overlap is attested by the reverse-direction
      edge; the pair contributes neither ``matched_upstream`` nor
      ``INCOMPATIBLE``. From the OTHER party's perspective, the same
      edge classifies as ``HAS_SERIAL`` and serializes correctly.
    * **PathClaimOverride consultation.** When an active override
      pair (
      :func:`yoke_core.domain.path_claims_override.is_active_override`
      ) names ``(candidate_claim_id, blocking_claim_id)``, the pair is
      treated as serial regardless of dep-graph state. ``exclude_claim_id``
      doubles as the candidate's claim id at activate time.
    """
    if not target_ids:
        return OverlapClassification.NONE

    expanded_targets = expand_lineage(conn, target_ids)

    states_to_check = (
        _ACTIVATION_CONFLICT_STATES if phase == "activate" else _NON_TERMINAL_STATES
    )
    placeholders = ",".join(_p(conn) for _ in states_to_check)
    same_target_clauses = (
        f"AND pc.id <> {_p(conn)}" if exclude_claim_id is not None else ""
    )
    frozen_join = ""
    frozen_filter = ""
    if _column_exists(conn, "items", "frozen"):
        frozen_join = " LEFT JOIN items owner ON owner.id = pc.owner_item_id"
        frozen_filter = " AND COALESCE(owner.frozen, 0) = 0"
    params: list = [integration_target, *list(states_to_check)]
    if exclude_claim_id is not None:
        params.append(exclude_claim_id)
    rows = conn.execute(
        f"SELECT pc.id, pc.state FROM path_claims pc"
        f"{frozen_join} "
        f"WHERE pc.integration_target = {_p(conn)} "
        f"AND pc.state IN ({placeholders}) AND pc.mode <> 'exception' "
        f"{same_target_clauses}{frozen_filter}",
        tuple(params),
    ).fetchall()

    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        CoordinationClassification,
        classify_inter_item_edges,
        has_forward_serial_edge,
    )
    from yoke_core.domain.path_claims_dependency_resolver import (
        _claim_owning_item,
    )
    from yoke_core.domain.path_claims_override import is_active_override

    # Resolve candidate_item_id once so the reverse-direction
    # upstream-of-`blocks` check below can run when callers (e.g.,
    # widen) only supply exclude_claim_id. The classifier resolves it
    # internally for its own walk; we need the same value for the
    # post-classifier disambiguation step.
    if candidate_item_id is None and exclude_claim_id is not None:
        candidate_item_id = _claim_owning_item(conn, exclude_claim_id)

    matched_upstream = False
    for row in rows:
        other_id = int(row[0])
        if not _candidate_intersects(
            conn,
            candidate_target_ids=expanded_targets,
            other_claim_id=other_id,
        ):
            continue
        # When the overlap is entirely on FAMILY_RENDER_TARGET paths AND
        # the two claims' coverage is disjoint at the seed-source layer,
        # the overlap is a deterministic-rendered false positive — skip
        # this other claim without contributing INCOMPATIBLE.
        if _is_render_target_only_overlap(
            conn,
            candidate_target_ids=expanded_targets,
            other_claim_id=other_id,
        ):
            continue
        if upstream_claim_id is not None and int(upstream_claim_id) == other_id:
            upstream_row = conn.execute(
                f"SELECT integration_target FROM path_claims WHERE id = {_p(conn)}",
                (upstream_claim_id,),
            ).fetchone()
            if upstream_row is not None and upstream_row[0] == integration_target:
                matched_upstream = True
                continue
        # Active override on the pair forces serial regardless of dep-edge
        # shape. Only meaningful when the candidate has a persisted claim id.
        if exclude_claim_id is not None and is_active_override(
            conn,
            path_claim_id=int(exclude_claim_id),
            blocking_claim_id=other_id,
        ):
            matched_upstream = True
            continue
        # Directional dep-graph classification: candidate-as-DEPENDENT of
        # a non-coordination edge serializes; a pair linked only by
        # coordination_only edges activates in parallel; candidate-as-
        # BLOCKER of a non-coordination edge means the candidate is
        # upstream and does not wait (the reverse-side caller serializes
        # correctly). True NO_EDGE (no item_dependencies row at all)
        # rejects as the door-lock safety net.
        inter_edge = classify_inter_item_edges(
            conn,
            candidate_claim_id=exclude_claim_id,
            candidate_item_id=candidate_item_id,
            blocking_claim_id=other_id,
        )
        if inter_edge is CoordinationClassification.HAS_SERIAL:
            matched_upstream = True
            continue
        if inter_edge is CoordinationClassification.COORDINATION_ONLY:
            continue
        # NO_EDGE has two sub-cases. Disambiguate by checking the reverse
        # direction: if a non-coord edge exists with the OTHER party as
        # DEPENDENT, the candidate is upstream-of-`blocks` and the pair
        # is attested.
        other_item_id = _claim_owning_item(conn, other_id)
        if (
            candidate_item_id is not None
            and other_item_id is not None
            and has_forward_serial_edge(
                conn,
                dependent_item_id=other_item_id,
                blocking_item_id=candidate_item_id,
            )
        ):
            continue
        return OverlapClassification.INCOMPATIBLE

    if matched_upstream:
        return OverlapClassification.SERIAL_VIA_DEPENDENCY
    return OverlapClassification.NONE


__all__ = [
    "OverlapClassification",
    "classify_overlap",
]
