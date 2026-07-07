"""HC-project-flow-migration-apply-coverage: declared models need a flow stage.

A project can declare a ``migration_model`` capability while no
``deployment_flow`` on the project carries a matching ``migration_apply``
stage at ``lifecycle_phase='implementing'``. The lifecycle gate in
``yoke_core.domain.db_mutation_gate_idea`` then refuses
``idea → refining-idea`` for every ticket with a real
``db_mutation_profile`` against that model — with no upstream signal at
install or authoring time.

Split out from ``doctor_hc_db_flows`` to keep that file under the
350-line cap. Re-exported through ``doctor_hc_db_flows.__all__`` and
``doctor_hc_db`` so ``doctor_registry`` retains its single import block.
"""

from __future__ import annotations

import json
from typing import List

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_project_flow_migration_apply_coverage(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-project-flow-migration-apply-coverage: declared migration models must be reachable via a flow stage.

    For every project that declares a ``migration_model`` capability, each
    declared model must be referenced by at least one ``migration_apply``
    stage at ``lifecycle_phase='implementing'`` on some flow attached to
    the same project. Two distinct failure shapes share one remediation
    surface:

    1. No flow stage references the declared model at all.
    2. A flow stage references the model but never at
       ``lifecycle_phase='implementing'`` (the only phase wired in governed DB-mutation gate).
    """
    name = "HC-project-flow-migration-apply-coverage"
    description = "Declared migration models are reachable via a flow stage"

    if not _base._table_exists(conn, "project_capabilities"):
        rec.record(name, description, "PASS",
                    "project_capabilities table does not exist — skipping")
        return
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record(name, description, "PASS",
                    "deployment_flows table does not exist — skipping")
        return

    cap_rows = query_rows(
        conn,
        "SELECT p.slug AS project, pc.project_id, pc.settings "
        "FROM project_capabilities pc "
        "JOIN projects p ON p.id = pc.project_id "
        "WHERE pc.type = 'migration_model' ORDER BY p.slug",
    )
    if not cap_rows:
        rec.record(name, description, "PASS",
                    "no projects declare a migration_model capability")
        return

    flow_rows = query_rows(
        conn,
        "SELECT df.id, p.slug AS project, df.stages "
        "FROM deployment_flows df "
        "JOIN projects p ON p.id = df.project_id "
        "ORDER BY p.slug, df.id",
    )
    # Pre-index migration_apply stages per project.
    by_project: dict = {}
    for row in flow_rows:
        proj = row["project"]
        if not proj:
            continue
        raw_stages = row["stages"]
        if not raw_stages:
            continue
        try:
            stages = json.loads(raw_stages)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(stages, list):
            continue
        for stage in stages:
            if not isinstance(stage, dict) or stage.get("kind") != "migration_apply":
                continue
            model_name = stage.get("model_name")
            phase = stage.get("lifecycle_phase") or ""
            by_project.setdefault(proj, []).append(
                {"flow_id": row["id"], "model_name": model_name, "phase": phase}
            )

    issues: List[str] = []
    for cap in cap_rows:
        project = cap["project"]
        raw = cap["settings"]
        try:
            parsed = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            issues.append(
                f"- project '{project}': migration_model capability has "
                "malformed settings JSON; cannot validate coverage"
            )
            continue
        models = parsed.get("models") if isinstance(parsed, dict) else None
        if not isinstance(models, dict) or not models:
            issues.append(
                f"- project '{project}': migration_model capability declares "
                "no models; expected at least one"
            )
            continue
        project_stages = by_project.get(project, [])
        project_flow_ids = sorted({
            row["id"] for row in flow_rows if row["project"] == project
        })
        flow_list = ", ".join(project_flow_ids) if project_flow_ids else "(none)"
        for model_name in sorted(models.keys()):
            matches = [s for s in project_stages if s["model_name"] == model_name]
            if not matches:
                issues.append(
                    f"- project '{project}': declared model '{model_name}' has "
                    f"no migration_apply stage on any project flow. Tickets "
                    f"with a real db_mutation_profile against this model jam "
                    f"at idea. Add the stage to one of: {flow_list}."
                )
                continue
            phases = {m["phase"] for m in matches}
            if "implementing" not in phases:
                covering = ", ".join(sorted({m["flow_id"] for m in matches}))
                issues.append(
                    f"- project '{project}': declared model '{model_name}' has "
                    f"migration_apply stage(s) on flow(s) {covering} but never "
                    f"at lifecycle_phase='implementing' (found: {sorted(phases)}). "
                    "Only 'implementing' is wired in governed DB-mutation gate; tickets with a real "
                    "db_mutation_profile against this model jam at idea."
                )

    if issues:
        rec.record(name, description, "FAIL", "\n".join(issues))
    else:
        rec.record(name, description, "PASS", "")


__all__ = ("hc_project_flow_migration_apply_coverage",)
