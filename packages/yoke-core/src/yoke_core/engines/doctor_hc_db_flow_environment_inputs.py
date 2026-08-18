"""Deployment-flow environment-input health check.

A release route names the environment it deploys to as a stage input, and the
workflow it dispatches validates that word against the environment names it
serves before doing any work. The two agree only by convention, so renaming an
environment on one side leaves the other sending a word that no longer resolves
and the release stops at its own guard having deployed nothing.

This check reads the routes rather than the workflow files, because the route is
the surface that drifts silently: a workflow rename is a reviewed diff, while a
route lives in the control plane and can outlive the vocabulary it was written
against.
"""

from __future__ import annotations

import json
from typing import Any, List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.environment_reference import registered_names
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

import yoke_core.engines.doctor_report as _base


_TITLE = "Flow stages dispatch a registered environment name"


def _is_placeholder(value: str) -> bool:
    """A run-time substitution, not a literal environment name.

    A route may defer the environment to the run that starts it, writing the
    stage input as a ``{placeholder}`` the runner fills from the run's typed
    environment reference. That value is resolved authority already and has no
    literal to check here.
    """
    return value.startswith("{") and value.endswith("}")


def _environment_inputs(stages: Any) -> List[tuple[str, str, str]]:
    """Every (stage, input key, literal value) naming an environment."""
    found: List[tuple[str, str, str]] = []
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        stage_name = str(stage.get("name") or "?")
        inputs = stage.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if "environment" not in str(key).lower():
                continue
            if not isinstance(value, str):
                continue
            found.append((stage_name, str(key), value))
    return found


def hc_flow_stage_environment_input(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-flow-stage-environment-input: routes dispatch registered environment names."""
    if not _base._table_exists(conn, "deployment_flows") or not _base._table_exists(
        conn, "environments"
    ):
        rec.record(
            "HC-flow-stage-environment-input", _TITLE, "PASS",
            "deployment_flows or environments table does not exist — skipping",
        )
        return

    # Only active routes: a disabled definition is retained history that can no
    # longer start a run, and its definition is immutable by design.
    rows = query_rows(
        conn,
        "SELECT df.id, df.project_id, p.slug AS project, df.stages "
        "FROM deployment_flows df "
        "JOIN projects p ON p.id = df.project_id "
        "WHERE df.status = 'active' ORDER BY p.slug, df.id",
    )

    known: dict[int, list[str]] = {}
    issues: List[str] = []
    for row in rows:
        try:
            stages = json.loads(row["stages"])
        except (TypeError, ValueError):
            # Stage JSON validity is HC-flow-stage-json's subject; reporting it
            # here too would give one defect two voices.
            continue
        pairs = _environment_inputs(stages)
        if not pairs:
            continue
        project_id = int(row["project_id"])
        if project_id not in known:
            known[project_id] = registered_names(conn, project_id=project_id)
        names = known[project_id]
        for stage_name, key, value in pairs:
            if _is_placeholder(value):
                continue
            if value in names:
                continue
            registered = ", ".join(names) if names else "(none registered)"
            issues.append(
                f"- {row['project']}/{row['id']} stage '{stage_name}': "
                f"{key}='{value}' is not a registered environment name. "
                f"Project '{row['project']}' registers: {registered}."
            )

    if issues:
        rec.record("HC-flow-stage-environment-input", _TITLE, "FAIL", "\n".join(issues))
    else:
        rec.record("HC-flow-stage-environment-input", _TITLE, "PASS", "")


__all__ = ("hc_flow_stage_environment_input",)
