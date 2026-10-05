"""The invariant behind carried enrollment: deliverable code it did not admit.

Enrollment completes a run's membership from its own pinned lineage. This is
the check that nothing was waived by silence -- code the candidate carries that
is delivery-ready, that no release holds, and that the run still omits stops
the run instead of shipping unowned. It repeats enrollment's own subtraction of
held landings so the two readers can never disagree about what the candidate
obliges, and it accepts the same injected custody resolution so repeating that
question costs no second source walk.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import (
    completion_flow_refusal,
)
from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    project_carried_sets,
)
from yoke_core.domain.deployment_run_carried_work import (
    derive_carried_work_safely,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    inherited_frozen_membership,
    item_requires_release_membership,
    member_ids,
    requires_release_admission,
)
from yoke_core.domain.deployment_run_membership_removals import (
    removed_item_ids,
)
from yoke_core.domain.deployment_run_dependency_readiness import (
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    held_candidate_ids,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def carried_membership_refusal(
    conn: Any,
    run_id: str,
    *,
    carried_work: Mapping[str, Any] | None = None,
    custody: CustodyResolution | None = None,
) -> str | None:
    """Return an actionable refusal for unresolved or omitted deliverable code.

    Pass *custody* to reuse a resolution the caller already walked; omitting it
    walks the run's candidate custody again.
    """
    if not requires_release_admission(conn, run_id):
        return None
    if not _column_exists(conn, "deployment_runs", "composition_resolution"):
        return None
    run = conn.execute(
        f"SELECT release_lineage,composition_resolution FROM deployment_runs "
        f"WHERE id={_p(conn)}",
        (run_id,),
    ).fetchone()
    if run is None:
        return f"deployment run {run_id!r} not found"
    lineage = str(_cell(run, "release_lineage", 0) or "").strip()
    resolution = str(_cell(run, "composition_resolution", 1) or "").strip()
    if not lineage:
        return None
    payload = dict(carried_work or derive_carried_work_safely(conn, run_id))
    project_sets = project_carried_sets(payload)
    if not resolution:
        problems: list[str] = []
        for project_set in project_sets:
            derivation = project_set.get("derivation") or {}
            reason = str(derivation.get("reason") or "unknown")
            project = str(project_set.get("project") or "run project")
            if not bool(derivation.get("contents_known")):
                recovery = str(derivation.get("recovery") or "").strip()
                problems.append(
                    f"{project} carried-code membership is {reason}. "
                    + (recovery or "Repair source access, then revalidate composition.")
                )
        if problems:
            return f"deployment run {run_id!r} carried-work blockers:\n" + "\n".join(
                problems
            )
    if inherited_frozen_membership(conn, run_id):
        # A retry delivers exactly what its predecessor froze. Re-scanning
        # against a baseline that has moved since would name items this
        # candidate never promised, so the inherited answer stands.
        return None
    members = set(member_ids(conn, run_id))
    eligible = sorted(
        {
            int(entry["item_id"])
            for project_set in project_sets
            for entry in project_set.get("items") or []
            if item_requires_release_membership(conn, int(entry["item_id"]))
        }
        - held_candidate_ids(conn, run_id, custody=custody)
        - removed_item_ids(conn, run_id)
    )
    blocked = {
        dependent for dependent, _, _ in unshipped_dependency_pairs(conn, eligible)
    }
    eligible = [item_id for item_id in eligible if item_id not in blocked]
    for item_id in eligible:
        if refusal := completion_flow_refusal(conn, item_id):
            return f"deployment run {run_id!r} carries {refusal}"
    omitted = [item_id for item_id in eligible if item_id not in members]
    if not omitted:
        return None
    labels = ", ".join(render_item_ref(conn, int(item_id)) for item_id in omitted)
    why = carried_enrollment_blocked(conn, run_id) or (
        "they became deliverable after this run composed its membership"
    )
    return (
        f"deployment run {run_id!r} omits delivery-ready carried work: {labels}; "
        f"automatic enrollment did not add them ({why}). Re-run the deployment "
        "start so admission enrolls them, attach them, or choose a candidate "
        "that excludes their code. An already-done item is never one of them: "
        "it cannot be newly admitted, and its code travels under the run's "
        "pinned release lineage"
    )


__all__ = ["carried_membership_refusal"]
