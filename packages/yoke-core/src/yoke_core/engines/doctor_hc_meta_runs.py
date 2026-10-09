"""Meta health checks — done-item run/deferral hygiene.

Extracted from ``doctor_hc_meta`` to keep that module under the file-line cap.
This sibling owns the post-done-state hygiene HCs:

- ``hc_undeployed_done`` — done items missing ``deployed_to`` on projects with flows.
- ``hc_orphaned_done_items`` — done items with active lanes (bypass signal).
- ``hc_deferred_items`` — deferral language hygiene on done epics.

``doctor.py`` continues to import these symbols via ``doctor_hc_meta`` for
registration parity; this module is the authoritative source.
"""

from __future__ import annotations

from typing import List
from datetime import timedelta
from yoke_contracts.timestamps import InvalidInstant, parse_instant

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.deferred_item_tracking import (
    deferral_findings,
    describe_finding,
    item_deferral_text,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_behavior import generates_task_graph
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_PINNED_WORKFLOW_COLUMNS = (
    "i.workflow_id, i.workflow_version_id, v.version, "
    "v.definition_json, v.definition_digest"
)


def _completed_workflow_rows(rows, *, task_graph_only: bool = False):
    for row in rows:
        runtime = workflow_runtime_from_row(row)
        if row["status"] not in runtime.terminal_stage_ids:
            continue
        if task_graph_only and not generates_task_graph(runtime):
            continue
        yield row


def hc_undeployed_done(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-undeployed-done: Undeployed done items."""
    issues: List[str] = []
    now = _base.utc_now()
    # Default warn threshold: 7 days
    warn_age = timedelta(days=7)
    min_item_id = _base._read_int_cutoff("hc_undeployed_done_min_item_id")

    rows = query_rows(
        conn,
        "SELECT i.id, i.status, i.deployed_to, i.updated_at, i.project_id, "
        + _PINNED_WORKFLOW_COLUMNS
        + " FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        "JOIN workflow_versions v ON v.id = i.workflow_version_id",
    )
    for row in _completed_workflow_rows(rows):
        item_id = row["id"]
        if min_item_id is not None and item_id < min_item_id:
            continue
        deployed = row["deployed_to"]
        if deployed and deployed != "null":
            continue
        # Skip projects without deployment flows.
        flow_count = (
            query_scalar(
                conn,
                f"SELECT count(*) FROM deployment_flows WHERE project_id={_p(conn)}",
                (row["project_id"],),
            )
            if _base._table_exists(conn, "deployment_flows")
            else 0
        )
        if not flow_count or int(flow_count) == 0:
            continue

        updated = row["updated_at"]
        public_ref = render_item_ref(conn, int(item_id))
        if updated is None:
            issues.append(
                f"- {public_ref}: missing update clock; deployment age unknown"
            )
            continue
        try:
            age = now - parse_instant(updated)
        except InvalidInstant:
            issues.append(f"- {public_ref}: invalid_instant — update clock refused")
            continue
        if age >= warn_age:
            issues.append(
                f"- {public_ref}: done for {age.days} days with no deployed_to value"
            )

    if issues:
        rec.record(
            "HC-undeployed-done", "Undeployed done items", "WARN", "\n".join(issues)
        )
    else:
        rec.record("HC-undeployed-done", "Undeployed done items", "PASS", "")


def hc_orphaned_done_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-done-items: Done items with signs of bypassed ceremony.

    DB-only portion: done items with universal lanes still active.
    (Branch check requires git and is deferred to a later task.)
    """
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT i.id, i.status, i.title, iw.branch, iw.path, "
        + _PINNED_WORKFLOW_COLUMNS
        + " FROM items i "
        "JOIN item_worktrees iw ON iw.item_id = i.id "
        "JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "WHERE iw.state = 'active' "
        "ORDER BY i.id, iw.id",
    )
    for row in _completed_workflow_rows(rows):
        issues.append(
            f"- {render_item_ref(conn, int(row['id']))} ({row['title']}): worktree lane "
            f"'{row['branch']}' remains active "
            f"— ceremony may have been bypassed"
        )

    if issues:
        rec.record(
            "HC-orphaned-done-items",
            "Done items with signs of bypassed ceremony",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-orphaned-done-items",
            "Done items with signs of bypassed ceremony",
            "PASS",
            "",
        )


def hc_deferred_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-deferred-items: Deferred items enforcement for done epics."""
    issues: List[str] = []
    rows = query_rows(
        conn,
        f"SELECT i.id, i.status, {_PINNED_WORKFLOW_COLUMNS} "
        "FROM items i JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "ORDER BY i.id",
    )
    for row in _completed_workflow_rows(rows, task_graph_only=True):
        text = item_deferral_text(conn, int(row["id"]))
        ref = render_item_ref(conn, int(row["id"]))
        issues.extend(
            f"- {ref}: {describe_finding(finding)}"
            for finding in deferral_findings(text)
        )

    if issues:
        rec.record(
            "HC-deferred-items",
            "Deferred items enforcement (done epics)",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-deferred-items", "Deferred items enforcement (done epics)", "PASS", ""
        )
