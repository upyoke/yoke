"""Doctor health check — per-project CI workflow capability is configured.

HC-projects-ci-workflow-configured WARNs when a project row has
``github_repo`` set but no ``ci_workflow_file`` capability declared.

This is a configuration nudge, not a correctness block: the pre-merge
CI gate in ``.agents/skills/yoke/usher/collect.md`` silently skips
the advisory check when the capability is absent, so a missing row
means usher cannot verify cloud CI for that project's PRs. WARN
(not FAIL) so doctor surfaces it without blocking any green status.

PASSes silently when no qualifying projects exist (the check makes no
sense for projects that have not declared a GitHub repo).
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.github_actions_workflow_inspection import (
    QUEUE_REFUSING_REASON_CODES,
    REFUSING_REASON_CODES,
    inspect_declared_workflow,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)
from yoke_core.domain.qa_command_scope_routing import (
    capability_settings,
    default_workflow,
    lands_through_merge_queue,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _table_exists,
)


CHECK_ID = "projects-ci-workflow-configured"
CHECK_NAME = "Per-project CI workflow capability"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _unreachable_declarations(conn, projects) -> list[tuple[str, str]]:
    """Declared workflows this host can read and the gate could not run.

    A declaration that was true when it was written stops being true when the
    workflow is renamed or loses the trigger the gate starts it with, and
    nothing else notices until an item's verification fails. Only projects
    whose checkout is on this host can be read; the rest are silent here
    rather than guessed at.
    """
    findings: list[tuple[str, str]] = []
    for row in projects:
        project_id = int(row["id"])
        checkout = checkout_for_project_id(project_id)
        if checkout is None:
            continue
        declared = default_workflow(capability_settings(conn, project_id))
        if not declared:
            continue
        inspection = inspect_declared_workflow(declared, checkout=checkout)
        refusing = (
            QUEUE_REFUSING_REASON_CODES
            if lands_through_merge_queue(conn, project_id)
            else REFUSING_REASON_CODES
        )
        if inspection.reason_code in refusing:
            findings.append((str(row["slug"]), inspection.message))
    return findings


def _unreachable_detail(findings: list[tuple[str, str]]) -> str:
    lines = [
        f"Projects whose declared '{CI_WORKFLOW_CAPABILITY_TYPE}' workflow "
        "cannot be reached by the verification gate:"
    ]
    lines.extend(f"  {slug}: {message}" for slug, message in findings)
    return "\n".join(lines)


def hc_projects_ci_workflow_configured(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-projects-ci-workflow-configured."""
    if not (
        _table_exists(conn, "projects")
        and _table_exists(conn, "project_capabilities")
    ):
        return

    projects_with_repo = query_rows(
        conn,
        "SELECT id, slug FROM projects "
        "WHERE github_repo IS NOT NULL AND github_repo <> '' "
        "ORDER BY slug",
    )
    if not projects_with_repo:
        rec.record(CHECK_ID, CHECK_NAME, "PASS",
                   "No projects declare github_repo; nothing to nudge.")
        return

    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT p.slug FROM projects p "
        "LEFT JOIN project_capabilities pc "
        f"  ON pc.project_id = p.id AND pc.type = {p} "
        "WHERE p.github_repo IS NOT NULL AND p.github_repo <> '' "
        "AND pc.project_id IS NULL "
        "ORDER BY p.slug",
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    )
    missing = [str(row["slug"]) for row in rows]
    unreachable = _unreachable_declarations(conn, projects_with_repo)

    if not missing and not unreachable:
        rec.record(CHECK_ID, CHECK_NAME, "PASS",
                   "All projects with github_repo declare "
                   f"a '{CI_WORKFLOW_CAPABILITY_TYPE}' capability, and every "
                   "declaration readable here names a workflow the "
                   "verification gate can reach.")
        return

    if not missing:
        rec.record(CHECK_ID, CHECK_NAME, "WARN", _unreachable_detail(unreachable))
        return

    detail = (
        "Projects with github_repo but no "
        f"'{CI_WORKFLOW_CAPABILITY_TYPE}' capability: "
        f"{', '.join(missing)}.\n"
        "  The pre-merge CI gate in usher cannot verify cloud CI for "
        "these projects until the workflow filename is declared.\n"
        f"  Seed via: yoke projects capability has --project <id> "
        f"--cap-type {CI_WORKFLOW_CAPABILITY_TYPE}\n"
        "  (or use the operator/debug adapter "
        "`python3 -m yoke_core.domain.projects "
        f"capability-merge-settings <id> {CI_WORKFLOW_CAPABILITY_TYPE} "
        "--set workflow_file=<filename>`)"
    )
    if unreachable:
        detail = f"{detail}\n{_unreachable_detail(unreachable)}"
    rec.record(CHECK_ID, CHECK_NAME, "WARN", detail)


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "hc_projects_ci_workflow_configured",
]
