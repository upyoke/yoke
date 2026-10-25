"""Which run already owns one merged item's delivery, before another starts.

``start-for-item`` creates a run only when nothing already owes the item its
delivery, so repeating it while that delivery is active does no second piece
of work. Two existing facts answer, in order:

1. Landing custody: a live or succeeded run that names the item and contains
   its landing holds it. That run is the answer, whatever project owns it.
2. Bound sources: a live run of another project that binds this project's
   source ships this project's code to the same environment. A Yoke release
   that ships Platform through its pin is one; the rule is the generic
   bound-source record, not a project name. When the commit it pinned
   contains the landing, that run carries the item. When it does not, or
   containment cannot be read, starting this project's own flow would race
   that release, so the start refuses, names the run and the commit it
   pinned, and never claims the item is included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.refusal_recovery import compose_refusal

#: Another project's live release binds this project's source without the item.
CARRIER_IN_FLIGHT = "bound_release_in_flight"


@dataclass(frozen=True)
class DeliveryOwner:
    """The run that owns the delivery, or the release blocking a new one."""

    run_id: str
    run_status: str
    project: str
    #: True when the run holds or carries the item; False when it blocks.
    carries: bool
    message: str
    code: str = ""


def _live_binding_runs(
    conn: Any, project_id: int, environment: str
) -> list[dict[str, Any]]:
    from yoke_core.domain.runs import ACTIVE_RUN_STATUSES

    statuses = sorted(ACTIVE_RUN_STATUSES)
    holes = ", ".join("%s" for _ in statuses)
    rows = conn.execute(
        "SELECT r.id, r.status, r.project_id, p.slug, "
        "COALESCE(r.bound_sources, '') AS bound_sources "
        "FROM deployment_runs r JOIN projects p ON p.id = r.project_id "
        "LEFT JOIN environments e ON e.id = r.target_environment_id "
        f"WHERE r.status IN ({holes}) AND r.project_id <> %s "
        "AND COALESCE(r.bound_sources, '') <> '' "
        "AND e.name IS NOT DISTINCT FROM %s "
        "ORDER BY r.created_at DESC, r.id DESC",
        (*statuses, int(project_id), environment or None),
    ).fetchall()
    return [
        {
            "id": str(row[0]),
            "status": str(row[1]),
            "project_id": int(row[2]),
            "slug": str(row[3]),
            "bound_sources": row[4],
        }
        for row in rows
    ]


def _held(ref: str, custody: Any, conn: Any) -> DeliveryOwner:
    row = conn.execute(
        "SELECT p.slug FROM deployment_runs r JOIN projects p "
        "ON p.id = r.project_id WHERE r.id = %s",
        (custody.run_id,),
    ).fetchone()
    project = str(row[0]) if row else ""
    done = custody.run_status == "succeeded"
    return DeliveryOwner(
        run_id=custody.run_id,
        run_status=custody.run_status,
        project=project,
        carries=True,
        message=(
            f"{ref} is already a member of deployment run {custody.run_id} "
            f"({project}, {custody.run_status}), whose release contains its "
            f"merge {custody.landing_sha}; "
            + (
                "that delivery already happened, so no run was created."
                if done
                else "that delivery is in progress, so no second run was created. "
                f"Follow it with `yoke deployment-runs get {custody.run_id}`."
            )
        ),
    )


def _bound(
    ref: str, conn: Any, project_id: int, landing: str, run: dict[str, Any]
) -> Optional[DeliveryOwner]:
    from yoke_core.domain.deployment_run_candidate_containment import (
        CandidateContainment,
    )
    from yoke_core.domain.deployment_run_project_sources import recorded_source_sha

    pinned = recorded_source_sha(run, project_id)
    if not pinned:
        return None
    verdict = CandidateContainment(
        conn, project_id, candidate_lineage=pinned
    ).contains(landing)
    where = f"deployment run {run['id']} ({run['slug']}, {run['status']})"
    if verdict.contained:
        return DeliveryOwner(
            run_id=run["id"],
            run_status=run["status"],
            project=run["slug"],
            carries=True,
            message=(
                f"{ref} rides {where}: it binds this project at {pinned}, "
                f"which contains its merge {landing}, so no competing run was "
                f"created. Follow it with `yoke deployment-runs get {run['id']}`."
            ),
        )
    finding = (
        f"its pinned commit {pinned} does not contain {ref}'s merge {landing}"
        if verdict.state == "not_contained"
        else f"whether its pinned commit {pinned} contains {ref}'s merge "
        f"{landing} could not be read ({verdict.reason}: {verdict.recovery})"
    )
    return DeliveryOwner(
        run_id=run["id"],
        run_status=run["status"],
        project=run["slug"],
        carries=False,
        code=CARRIER_IN_FLIGHT,
        message=compose_refusal(
            f"{where} is in flight and ships this project's source to the "
            f"same environment, but {finding}, so it does not carry {ref}. "
            "A run of this project's own flow now would compete with that "
            "release. Nothing was created.",
            recovery=(
                f"let {run['id']} finish (`yoke deployment-runs get "
                f"{run['id']}`), then run `yoke deployment-runs start-for-item "
                f"{ref}` again: the next {run['slug']} release that binds a "
                "commit containing the merge carries it, or this project's "
                "own flow starts once no such release is in flight."
            ),
        ),
    )


def delivery_owner(
    item_id: int, project: str, environment: str
) -> Optional[DeliveryOwner]:
    """The run already owning *item_id*'s delivery, a blocker, or ``None``."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.delivery_landing_custody import HELD, landing_custody
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.project_identity_item_ref import item_ref_for_id

    ref = item_ref_for_id(item_id)
    conn = connect(None)
    try:
        project_id = resolve_project_id(conn, project)
        custody = landing_custody(conn, project_id=project_id, item_ids=[item_id])
        held = custody.get(int(item_id))
        if held is None or not held.landing_sha:
            return None
        if held.state == HELD:
            return _held(ref, held, conn)
        for run in _live_binding_runs(conn, project_id, environment):
            owner = _bound(ref, conn, project_id, held.landing_sha, run)
            if owner is not None:
                return owner
        return None
    finally:
        conn.close()


__all__ = ["CARRIER_IN_FLIGHT", "DeliveryOwner", "delivery_owner"]
