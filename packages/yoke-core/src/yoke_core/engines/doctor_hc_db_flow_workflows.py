"""Deployment-flow workflow file health check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

import yoke_core.engines.doctor_report as _base


def hc_flow_workflow_exists(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-flow-workflow-exists: Flow stage workflows exist in project repos."""

    if not _base._table_exists(conn, "deployment_flows"):
        rec.record(
            "HC-flow-workflow-exists", "Flow stage workflow files exist", "PASS", ""
        )
        return

    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record(
            "HC-flow-workflow-exists", "Flow stage workflow files exist", "PASS", ""
        )
        return

    fallback_repo = Path(repo_root)
    if _base._table_exists(conn, "projects"):
        rows = query_rows(
            conn,
            "SELECT df.id, p.id AS project_id, p.slug AS project, df.stages "
            "FROM deployment_flows df "
            "LEFT JOIN projects p ON p.id = df.project_id",
        )
    else:
        rows = query_rows(
            conn,
            "SELECT id, NULL AS project_id, NULL AS project, stages FROM deployment_flows",
        )

    issues: List[str] = []
    for row in rows:
        _append_workflow_issues(issues, row, fallback_repo)

    if issues:
        rec.record(
            "HC-flow-workflow-exists",
            "Flow stage workflow files exist",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-flow-workflow-exists", "Flow stage workflow files exist", "PASS", ""
        )


def _append_workflow_issues(
    issues: List[str],
    row,
    fallback_repo: Path,
) -> None:
    checkout = None
    if hasattr(row, "keys") and "project_id" in row.keys() and row["project_id"] is not None:
        checkout = checkout_for_project_id(int(row["project_id"]))
    project_repo = Path(checkout or fallback_repo)
    stages_json = row["stages"]
    if not stages_json:
        return
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, TypeError):
        return
    for stage in stages:
        wf = stage.get("workflow", "")
        if not wf:
            continue
        wf_path = _project_workflow_path(project_repo, wf)
        if wf_path.is_file():
            continue
        issues.append(
            f"- flow '{row['id']}' stage '{stage.get('name', '?')}': "
            f"workflow '{wf}' not found at {wf_path}"
        )


def _project_workflow_path(project_repo: Path, workflow: str) -> Path:
    """Return the expected project-repo path for a GitHub Actions workflow."""

    cleaned = workflow.strip()
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return candidate
    if "/" in cleaned:
        return project_repo / cleaned
    return project_repo / ".github" / "workflows" / cleaned
