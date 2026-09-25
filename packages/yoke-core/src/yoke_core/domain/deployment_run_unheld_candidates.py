"""Delivery-ready landings this run's candidate carries that no release holds.

Carried work answers "what did this run add over the run before it", and that
is the whole candidate set enrollment used to have. It is a question about a
commit RANGE, so it has a floor: the preceding succeeded release's lineage. A
landing behind that floor is outside every future range permanently. Once the
only run that ever named such an item ends without delivering it — cancelled,
superseded — nothing can propose it again, and three items sat at their
release wait for a day because the sole remaining recovery was an operator
remembering to attach them by hand.

This module asks the question that actually serves delivery, and it asks it
without a floor: which landings does this candidate carry that no live or
succeeded release holds? The answer is unioned into enrollment beside the
carried range, so a run start completes its own membership whether the work
landed since the last release or long before it.

Three things it deliberately does not do:

* It does not widen what "deliverable" means. Every candidate still passes
  ``item_requires_release_membership`` — the same pinned-workflow delivery
  readiness check every other admission uses.
* It does not enroll code this run is not shipping. Containment against the
  run's own pinned lineage is required, so a merge that landed after the
  candidate was pinned waits for the release that actually carries it.
* It does not re-enroll a landing somebody already holds. Custody lives in
  :mod:`delivery_landing_custody` and is asked per landing, so an item that
  merged again after joining a run enrolls for the new merge while one
  already being delivered is left alone.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.delivery_landing_custody import (
    landing_custody,
    merged_open_items,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    item_requires_release_membership,
)
from yoke_core.domain.deployment_run_project_sources import (
    carried_project_ids,
    run_source_sha,
)
from yoke_core.domain.project_identity import render_item_ref


def unheld_candidate_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    """Item ids this run should enroll that its carried range cannot see.

    Walks every project the run ships code for, because membership follows
    the code: a run binding another project's source delivers that project's
    merges too. Each project is asked against the commit THIS run pinned for
    it, never against a lineage belonging to the carrier.
    """
    found: set[int] = set()
    for project_id in carried_project_ids(conn, run_id):
        lineage = run_source_sha(conn, run_id, int(project_id))
        if not lineage:
            continue
        found.update(
            _project_candidates(
                conn, run_id, project_id=int(project_id), lineage=lineage
            )
        )
    return tuple(sorted(found))


def _project_candidates(
    conn: Any, run_id: str, *, project_id: int, lineage: str
) -> set[int]:
    """One project's unheld, deliverable landings inside this candidate."""
    deliverable = [
        int(record["id"])
        for record in merged_open_items(conn, project_id)
        if item_requires_release_membership(conn, int(record["id"]))
    ]
    if not deliverable:
        return set()
    custody = landing_custody(conn, project_id=project_id, item_ids=deliverable)
    walker = CandidateContainment(conn, project_id, candidate_lineage=lineage)
    found: set[int] = set()
    for item_id in deliverable:
        landing = custody[item_id]
        if landing.state == UNDETERMINED:
            raise ValueError(
                f"deployment run {run_id!r} cannot determine custody of "
                f"{render_item_ref(conn, item_id)}: {landing.reason}. "
                f"{landing.recovery}"
            )
        if not landing.enrollable:
            continue
        if not landing.landing_sha:
            raise ValueError(
                f"deployment run {run_id!r} cannot attribute "
                f"{render_item_ref(conn, item_id)}: its merged landing has no "
                "commit identity; repair its merge receipt and retry"
            )
        verdict = walker.contains(landing.landing_sha)
        if verdict.state == UNDETERMINED:
            raise ValueError(
                f"deployment run {run_id!r} cannot compare the pinned "
                f"candidate with {render_item_ref(conn, item_id)}: "
                f"{verdict.reason}. {verdict.recovery}"
            )
        if verdict.contained:
            found.add(item_id)
    return found


__all__ = ["unheld_candidate_ids"]
