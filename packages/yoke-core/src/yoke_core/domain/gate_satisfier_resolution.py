"""Resolve and record item-scoped satisfier ladders on the server.

Item-scoped done gates come through this module. It refreshes the project's
derived facts at the point they are consumed, composes the item and
caller-observed facts, resolves the highest reachable rung, and persists the
result. Keeping that sequence server-side gives local and
HTTPS callers the same answer and prevents the derived-fact registry from
remaining an unused cache while ladders silently rely on live observations.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.gate_satisfier_facts import load_project_facts
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.gate_satisfier_facts import (
    OBSERVED_MERGE_RECORDED,
    OBSERVED_NO_IMPLEMENTATION_BRANCH,
)
from yoke_core.domain.gate_satisfier_ladder import (
    SatisfierRecordingScope,
    render_refusal,
    resolve_ladder,
)
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    LADDERS,
    OBLIGATION_DELIVERY_EVIDENCE,
    OBLIGATION_DONE_MERGE_EVIDENCE,
    RUNG_AGENT_ATTESTED,
)
from yoke_core.domain.gate_satisfier_stamp import (
    read_rungs,
    record_refusal,
    record_rung,
)
from yoke_core.domain.project_derived_facts import converge_derived_facts


class UnknownGateObligation(LookupError):
    """The caller named no registered satisfier ladder."""


class ItemResolutionTargetMissing(LookupError):
    """The item or its project context could not be resolved."""


class ResolutionOnlyObligation(ValueError):
    """An item-stamp surface was asked to record a project-only ladder."""


class DerivedFactsNotConverged(RuntimeError):
    """The extended project registry could not refresh for a ladder run."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_project(conn: Any, item_id: int) -> tuple[int, str]:
    marker = _p(conn)
    row = conn.execute(
        "SELECT i.project_id, p.slug FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        raise ItemResolutionTargetMissing(
            f"{render_item_ref(conn, item_id)} has no project row, so the satisfier registry "
            "cannot be resolved"
        )
    return int(row[0]), str(row[1] or "")


def resolve_and_record_item_rung(
    conn: Any,
    *,
    item_id: int,
    obligation: str,
    observed: Mapping[str, Tuple[bool, str]],
    target_status: str = "",
) -> Dict[str, Any]:
    """Resolve one item-scoped obligation and durably record its outcome."""
    ladder = LADDERS.get(str(obligation))
    if ladder is None:
        raise UnknownGateObligation(
            f"no satisfier ladder is registered for obligation "
            f"{obligation!r}; known obligations are "
            f"{', '.join(sorted(LADDERS))}"
        )
    if ladder.recording_scope is not SatisfierRecordingScope.ITEM:
        raise ResolutionOnlyObligation(
            f"obligation {ladder.obligation!r} is "
            f"{ladder.recording_scope.value}: {ladder.recording_reason}"
        )

    project_id, project_slug = _item_project(conn, item_id)
    warnings: list[str] = []
    converge_derived_facts(conn, project_id, warnings)
    if warnings:
        raise DerivedFactsNotConverged(
            f"derived project facts could not converge while resolving "
            f"{ladder.obligation!r}: {'; '.join(warnings)}. Repair the "
            "control-plane schema or fact source and retry; an empty cache "
            "must not become the permanent registry."
        )

    facts = load_project_facts(
        conn,
        project_id,
        item_id=int(item_id),
        observed=observed,
    )
    resolution = resolve_ladder(ladder, facts)
    if not resolution.satisfied:
        record_refusal(
            conn,
            item_id=int(item_id),
            ladder=ladder,
            resolution=resolution,
            target_status=target_status,
            project=project_slug,
        )
        return {
            "obligation": ladder.obligation,
            "satisfied": False,
            "refusal": render_refusal(ladder, resolution),
            "facts": resolution.facts,
        }

    stamped = record_rung(
        conn,
        item_id=int(item_id),
        ladder=ladder,
        resolution=resolution,
        target_status=target_status,
        project=project_slug,
    )
    return {
        "obligation": ladder.obligation,
        "satisfied": True,
        "rung_id": resolution.rung_id,
        "detail": ladder.rung(resolution.rung_id).summary,
        "facts": resolution.facts,
        "stamp_recorded": stamped,
    }


def _evidence_observations(
    *, merge_recorded: bool, agent_attested: bool
) -> Dict[str, Tuple[bool, str]]:
    """What one evidence record observes for the done ladders."""
    return {
        OBSERVED_MERGE_RECORDED: (
            bool(merge_recorded),
            "the standalone close-out records a landed merge"
            if merge_recorded
            else "the direct-evidence close-out records no merge",
        ),
        OBSERVED_NO_IMPLEMENTATION_BRANCH: (
            bool(agent_attested),
            "the close-out is agent-attested without an implementation merge"
            if agent_attested
            else "the close-out records an implementation merge",
        ),
    }


def record_done_evidence_rungs(
    conn: Any,
    *,
    item_id: int,
    merge_recorded: bool,
    agent_attested: bool,
) -> tuple[Dict[str, Any], ...]:
    """Stamp the done obligations one evidence write can answer for.

    Merge evidence is answered by the merge itself and must resolve here.
    Delivery evidence is stamped opportunistically, because for an item
    delivering through a release it is not yet answerable at merge time.
    """
    observed = _evidence_observations(
        merge_recorded=merge_recorded, agent_attested=agent_attested
    )

    def _stamp(obligation: str) -> Dict[str, Any]:
        return resolve_and_record_item_rung(
            conn,
            item_id=item_id,
            obligation=obligation,
            observed=observed,
            target_status="done",
        )

    merge_evidence = _stamp(OBLIGATION_DONE_MERGE_EVIDENCE)
    if not merge_evidence.get("satisfied"):
        raise ValueError(str(merge_evidence.get("refusal") or "").strip())
    _require_stamp(merge_evidence)
    outcomes = [merge_evidence]
    if merge_recorded:
        # Delivery is stamped here when the merge already answers for it --
        # a project with no deployment target delivers by landing. When it
        # does not, this write must not refuse: an item whose flow names a
        # real target delivers through a release, and the release wait it
        # sits in IS that pending delivery. Refusing here would make
        # recording a merge depend on the delivery that wait exists to
        # await, which a second landing on such an item can never satisfy.
        # The obligation still binds where it belongs: the done gate reads
        # the stamp back through `missing_done_evidence_rungs`, and no item
        # reaches a terminal stage without it. The release's own success
        # stamps it through `record_delivery_evidence_rung`.
        delivery = _stamp(OBLIGATION_DELIVERY_EVIDENCE)
        if delivery.get("satisfied"):
            _require_stamp(delivery)
            outcomes.append(delivery)
    return tuple(outcomes)


def record_delivery_evidence_rung(
    conn: Any, *, item_id: int, merge_recorded: bool
) -> Dict[str, Any]:
    """Stamp the delivery obligation once a release has actually delivered.

    A landing into a release wait cannot answer this — the release is what it
    waits for — so the release's own success is where the stamp belongs.
    Without it the done gate reads a missing rung on a delivered item and
    sends its holder back to re-run a merge only to record what the run
    already proved. Refuses rather than returning an unstamped success.
    """
    outcome = resolve_and_record_item_rung(
        conn,
        item_id=int(item_id),
        obligation=OBLIGATION_DELIVERY_EVIDENCE,
        observed=_evidence_observations(
            merge_recorded=merge_recorded, agent_attested=False
        ),
        target_status="done",
    )
    if not outcome.get("satisfied"):
        raise ValueError(str(outcome.get("refusal") or "").strip())
    _require_stamp(outcome)
    return outcome


def _require_stamp(outcome: Dict[str, Any]) -> None:
    """Refuse a resolved obligation whose durable row did not land."""
    if outcome.get("stamp_recorded"):
        return
    raise ValueError(
        f"obligation {outcome['obligation']!r} resolved to rung "
        f"{outcome.get('rung_id')!r}, but its durable "
        "item_gate_satisfactions row could not be recorded. Restart "
        "the server to converge the control-plane schema, then retry "
        "the close-out; an unstamped success is refused."
    )


def missing_done_evidence_rungs(
    conn: Any,
    *,
    item_id: int,
    merge_recorded: bool,
    agent_attested: bool,
) -> tuple[str, ...]:
    """Return canonical stamp defects for an execution-evidence record."""
    recorded = {
        row["obligation"]: row["rung_id"] for row in read_rungs(conn, int(item_id))
    }
    done_rung = recorded.get(OBLIGATION_DONE_MERGE_EVIDENCE, "")
    missing: list[str] = []
    if not done_rung:
        missing.append(OBLIGATION_DONE_MERGE_EVIDENCE)
    elif agent_attested and done_rung != RUNG_AGENT_ATTESTED:
        missing.append(f"{OBLIGATION_DONE_MERGE_EVIDENCE}:{RUNG_AGENT_ATTESTED}")
    elif merge_recorded and done_rung == RUNG_AGENT_ATTESTED:
        missing.append(f"{OBLIGATION_DONE_MERGE_EVIDENCE}:merged")
    if merge_recorded and OBLIGATION_DELIVERY_EVIDENCE not in recorded:
        missing.append(OBLIGATION_DELIVERY_EVIDENCE)
    return tuple(missing)


__all__ = [
    "DerivedFactsNotConverged",
    "ItemResolutionTargetMissing",
    "ResolutionOnlyObligation",
    "UnknownGateObligation",
    "missing_done_evidence_rungs",
    "record_delivery_evidence_rung",
    "record_done_evidence_rungs",
    "resolve_and_record_item_rung",
]
