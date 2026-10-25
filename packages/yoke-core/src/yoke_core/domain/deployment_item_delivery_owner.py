"""Which run already owns one merged item's delivery, before another starts.

``start-for-item`` creates a run only when nothing already owes the item its
delivery, so repeating it while that delivery is active does no second piece
of work. Two existing facts answer, in order:

1. Membership: a live or succeeded run to the same environment that names the
   item and pins a commit containing its landing holds it. A stage run that
   holds the item does not answer for production, so a stage-then-production
   pair still gets its production run.
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


def _runs(conn: Any, where: str, params: tuple) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT r.id, r.status, r.project_id, p.slug, "
        "COALESCE(r.release_lineage, '') AS release_lineage, "
        "COALESCE(r.bound_sources, '') AS bound_sources "
        "FROM deployment_runs r JOIN projects p ON p.id = r.project_id "
        "LEFT JOIN environments e ON e.id = r.target_environment_id "
        f"WHERE {where} AND e.name IS NOT DISTINCT FROM %s "
        "ORDER BY r.created_at DESC, r.id DESC",
        params,
    ).fetchall()
    keys = ("id", "status", "project_id", "slug", "release_lineage", "bound_sources")
    return [dict(zip(keys, row)) for row in rows]


def _member_runs(
    conn: Any, item_id: int, environment: str
) -> list[dict[str, Any]]:
    from yoke_core.domain.delivery_landing_custody import HOLDING_RUN_STATUSES

    statuses = sorted(HOLDING_RUN_STATUSES)
    holes = ", ".join("%s" for _ in statuses)
    return _runs(
        conn,
        "r.id IN (SELECT run_id FROM deployment_run_items WHERE item_id = %s) "
        f"AND r.status IN ({holes})",
        (int(item_id), *statuses, environment or None),
    )


def _live_binding_runs(
    conn: Any, project_id: int, environment: str
) -> list[dict[str, Any]]:
    from yoke_core.domain.runs import ACTIVE_RUN_STATUSES

    statuses = sorted(ACTIVE_RUN_STATUSES)
    holes = ", ".join("%s" for _ in statuses)
    return _runs(
        conn,
        f"r.status IN ({holes}) AND r.project_id <> %s "
        "AND COALESCE(r.bound_sources, '') <> ''",
        (*statuses, int(project_id), environment or None),
    )


def _held(ref: str, landing: str, run: dict[str, Any]) -> DeliveryOwner:
    done = run["status"] == "succeeded"
    where = f"deployment run {run['id']} ({run['slug']}, {run['status']})"
    return DeliveryOwner(
        run_id=run["id"],
        run_status=run["status"],
        project=run["slug"],
        carries=True,
        message=(
            f"{ref} is already a member of {where}, whose release contains "
            f"its merge {landing}; "
            + (
                "that delivery already happened, so no run was created."
                if done
                else "that delivery is in progress, so no second run was created. "
                f"Follow it with `yoke deployment-runs get {run['id']}`."
            )
        ),
    )


def _contains(conn: Any, project_id: int, pinned: str, landing: str) -> Any:
    from yoke_core.domain.deployment_run_candidate_containment import (
        CandidateContainment,
    )

    return CandidateContainment(
        conn, project_id, candidate_lineage=pinned
    ).contains(landing)


def _bound(
    ref: str, conn: Any, project_id: int, landing: str, run: dict[str, Any]
) -> Optional[DeliveryOwner]:
    from yoke_core.domain.deployment_run_project_sources import recorded_source_sha

    pinned = recorded_source_sha(run, project_id)
    if not pinned:
        return None
    verdict = _contains(conn, project_id, pinned, landing)
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
    from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.project_identity_item_ref import item_ref_for_id
    from yoke_core.domain.release_delivery_summary import (
        recorded_merge_shas_for_items,
    )

    ref = item_ref_for_id(item_id)
    conn = connect(None)
    try:
        project_id = resolve_project_id(conn, project)
        merges = recorded_merge_shas_for_items(conn, [int(item_id)])
        landing = (merges.get(int(item_id)) or ("",))[0]
        if not landing:
            return None
        for run in _member_runs(conn, item_id, environment):
            pinned = recorded_source_sha(run, project_id)
            if pinned and _contains(conn, project_id, pinned, landing).contained:
                return _held(ref, landing, run)
        for run in _live_binding_runs(conn, project_id, environment):
            owner = _bound(ref, conn, project_id, landing, run)
            if owner is not None:
                return owner
        return None
    finally:
        conn.close()


__all__ = ["CARRIER_IN_FLIGHT", "DeliveryOwner", "delivery_owner"]
