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
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.schema_common import _column_exists, _table_exists


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _settling_column(conn: Any) -> str:
    """Select the native settlement marker, or null before convergence."""
    if _column_exists(conn, "deployment_runs", "settling_at"):
        return "dr.settling_at"
    return "NULL AS settling_at"


def _bound_sources_column(conn: Any) -> str:
    """Select the recorded bound sources, or empty on an unconverged plane."""
    if _column_exists(conn, "deployment_runs", BOUND_SOURCES_FIELD):
        return f"COALESCE(dr.{BOUND_SOURCES_FIELD}, '') AS {BOUND_SOURCES_FIELD}"
    return f"'' AS {BOUND_SOURCES_FIELD}"


def completion_runs(
    conn: Any, item_id: int, *, include_qa: bool = False
) -> list[dict[str, Any]]:
    """Newest-first memberships that can close this item, of any status.

    Freshness is ``created_at`` (then ``id``). ``release_lineage`` and
    ``project_id`` name the candidate to ask containment about: the commit
    the run recorded for THIS item's project, which for an own-project run
    is the run's own lineage and for a carrier is the bound commit.
    """
    required = ("deployment_runs", "deployment_run_items")
    if not all(_table_exists(conn, table) for table in required):
        return []
    flows = item_closing_flows(conn, int(item_id))
    if not flows:
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT dr.id, dr.status, dr.current_stage, dr.project_id, "
        "COALESCE(dr.release_lineage, '') AS release_lineage, dr.flow, "
        "i.project_id AS item_project_id, "
        f"{_bound_sources_column(conn)}, {_settling_column(conn)} "
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


__all__ = ["completion_runs", "succeeded_completion_runs"]


def latest_qa_member_run(
    conn: Any, *, item_id: int, target_env: str
) -> dict[str, Any] | None:
    """Newest live or delivered member capable of answering this source target.

    An explicit target can be answered by a supplemental member. Untargeted
    intake remains with final delivery; neither a differently targeted sibling
    nor a cancelled attempt can shadow the member that owes this proof.
    """
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        run_qa_stage_targets,
        stage_target_admits,
    )

    from yoke_core.domain.deployment_qa_member_scope import legacy_run_credits_run_wide

    finals = completion_runs(conn, item_id)
    current_final = next(
        (run for run in finals if run["status"] not in {"failed", "cancelled"}), None
    )
    for run in completion_runs(conn, item_id, include_qa=bool(target_env)):
        if supplemental_qa_run(conn, run_id=run["id"], item_id=item_id) and (
            current_final is None
            or run["release_lineage"] != current_final["release_lineage"]
        ):
            continue
        if run["status"] in {"failed", "cancelled"}:
            continue
        if not target_env or (
            run in finals
            and legacy_run_credits_run_wide(conn, run_id=run["id"], item_id=item_id)
        ):
            return run
        environments, dynamic = run_qa_stage_targets(conn, run["id"])
        if stage_target_admits(target_env, environments=environments, dynamic=dynamic):
            return run
    return None
