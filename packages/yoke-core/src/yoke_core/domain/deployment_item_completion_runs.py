"""Every deployment run whose membership is completion authority for an item.

One walk, several readers. The done gate's delivery fact, the QA source
obligation, the delivery-evidence ladder and the release-wait close-out all
ask "which runs could close this item", and a copy of that walk per reader is
how the facts loader once counted only the item's own flow while the ladder
beside it also honoured a cross-project carrier — one release, two answers.

A membership closes the item when :func:`membership_closes_item` says so: a
run of one of the item's closing flows (its completion flow, or a retired
flow its pin followed there), or another project's run that recorded
a bound source commit for the item's project. Carried code alone, or a
same-project run of any other flow, is membership without authority.

A run that is settling (``settling_at`` set while it still reads
``executing``) passed every shared gate and is closing its members before it
may read ``succeeded``. Its delivery happened, so completion authority reads
it as succeeded; that is what lets those members' own done gates pass while
the run itself stays non-terminal until they have. Each entry still carries
``settling`` so producer gates can distinguish a delivery still closing its
members from a terminal run. Dependency readers instead consume the durable
completion attribution published with each item's successful done transition;
they do not re-evaluate the carrying run's later status.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import (
    item_closing_flows,
    membership_closes_item,
)
from yoke_core.domain.deployment_run_bound_sources import BOUND_SOURCES_FIELD
from yoke_core.domain.deployment_run_project_sources import (
    recorded_source_sha,
    run_recorded_and_delivered_shas,
)


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def completion_runs(
    conn: Any, item_id: int, *, include_qa: bool = False
) -> list[dict[str, Any]]:
    """Newest-first memberships that can close this item, of any status.

    Freshness is ``created_at`` (then ``id``). ``release_lineage`` and
    ``project_id`` name the candidate to ask containment about: the commit
    the run recorded for THIS item's project, which for an own-project run
    is the run's own lineage and for a carrier is the bound commit.
    """
    flows = item_closing_flows(conn, int(item_id))
    if not flows:
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT dr.id, dr.status, dr.current_stage, dr.project_id, "
        "COALESCE(dr.release_lineage, '') AS release_lineage, dr.flow, "
        "i.project_id AS item_project_id, "
        f"COALESCE(dr.{BOUND_SOURCES_FIELD}, '') AS {BOUND_SOURCES_FIELD}, "
        "dr.settling_at "
        "FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dr.id = dri.run_id "
        "JOIN items i ON i.id = dri.item_id "
        f"WHERE dri.item_id = {marker} "
        "ORDER BY dr.created_at DESC, dr.id DESC",
        (int(item_id),),
    ).fetchall()
    closing: list[dict[str, Any]] = []
    for row in rows:
        item_project = int(_row_value(row, "item_project_id", 6))
        source_sha = recorded_source_sha(
            {
                "project_id": _row_value(row, "project_id", 3),
                "release_lineage": _row_value(row, "release_lineage", 4),
                BOUND_SOURCES_FIELD: _row_value(row, BOUND_SOURCES_FIELD, 7),
            },
            item_project,
        )
        run_flow = str(_row_value(row, "flow", 5) or "")
        if not include_qa and (
            supplemental_qa_run(
                conn, run_id=str(_row_value(row, "id", 0)), item_id=item_id
            )
            or not membership_closes_item(
                run_flow=run_flow,
                closing_flows=flows,
                run_project_id=int(_row_value(row, "project_id", 3)),
                item_project_id=item_project,
                source_sha=source_sha,
            )
        ):
            continue
        status = str(_row_value(row, "status", 1) or "")
        settling = (
            status == "executing" and _row_value(row, "settling_at", 8) is not None
        )
        if settling:
            status = "succeeded"
        closing.append(
            {
                "id": str(_row_value(row, "id", 0) or ""),
                "status": status,
                "settling": settling,
                "current_stage": str(_row_value(row, "current_stage", 2) or ""),
                "project_id": item_project,
                "release_lineage": source_sha,
                "flow": run_flow,
            }
        )
    return closing


def succeeded_completion_runs(conn: Any, item_id: int) -> list[dict[str, Any]]:
    """The closing memberships whose run succeeded — delivery that happened."""
    return [
        run for run in completion_runs(conn, item_id) if run["status"] == "succeeded"
    ]


def current_final_run(finals: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest final membership that a failed or cancelled run cannot be."""
    return next(
        (run for run in finals if run["status"] not in {"failed", "cancelled"}), None
    )


def uncredited_supplemental_notice(conn: Any, *, run_id: str, item_id: int) -> str:
    """Name a supplemental membership whose proof close-out will not read, or ``''``.

    Close-out credits supplemental QA only on the current final run's pinned
    or delivered item-project commit. Said at the attach, the last moment the
    caller can pick a run on a commit the final delivery answers for.
    """
    if not supplemental_qa_run(conn, run_id=run_id, item_id=item_id):
        return ""
    final = current_final_run(completion_runs(conn, item_id))
    if final is None:
        return ""
    member = next(
        (
            run
            for run in completion_runs(conn, item_id, include_qa=True)
            if run["id"] == str(run_id)
        ),
        None,
    )
    if member is None:
        return ""
    credited = run_recorded_and_delivered_shas(conn, final["id"], final["project_id"])
    if member["release_lineage"] in credited:
        return ""
    from yoke_core.domain.project_identity import render_item_ref

    ref = render_item_ref(conn, item_id)
    return (
        f"Warning (supplemental_proof_not_credited): run {run_id} recorded "
        f"commit {member['release_lineage'] or '(none)'} for {ref}'s project, "
        f"but its final run {final['id']} pinned or delivered "
        f"{', '.join(sorted(credited)) or '(none)'}, so close-out will not "
        f"credit QA this run proves for {ref}. Remove it with `yoke "
        f"deployment-runs remove-item {run_id} {ref} --reason TEXT` and prove "
        "it on a run that records one of those commits."
    )


__all__ = [
    "completion_runs",
    "current_final_run",
    "succeeded_completion_runs",
    "uncredited_supplemental_notice",
]


def latest_qa_member_run(
    conn: Any, *, item_id: int, target_env: str
) -> dict[str, Any] | None:
    """Newest live or delivered member capable of answering this source target.

    An explicit target can be answered by a supplemental member that recorded
    the current final run's pinned or delivered item-project commit. Untargeted
    intake remains with final delivery; neither a differently targeted sibling
    nor a cancelled attempt can shadow the member that owes this proof.
    """
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        run_qa_stage_targets,
        stage_target_admits,
    )

    finals = completion_runs(conn, item_id)
    current_final = current_final_run(finals)
    credited = (
        frozenset()
        if current_final is None
        else run_recorded_and_delivered_shas(
            conn, current_final["id"], current_final["project_id"]
        )
    )
    for run in completion_runs(conn, item_id, include_qa=bool(target_env)):
        if (
            supplemental_qa_run(conn, run_id=run["id"], item_id=item_id)
            and run["release_lineage"] not in credited
        ):
            continue
        if run["status"] in {"failed", "cancelled"}:
            continue
        if not target_env:
            return run
        environments, dynamic = run_qa_stage_targets(conn, run["id"])
        if stage_target_admits(target_env, environments=environments, dynamic=dynamic):
            return run
    return None
