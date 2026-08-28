"""What a project must already have before a capability row may be created.

``capability_templates.requires`` has always carried this answer as data — the
merge-queue template names ``ci_workflow_file`` and ``github`` — and nothing
read it, so a project could declare the merge queue with neither. The gate
reads that declaration rather than restating any part of it in code, so a
template that changes its prerequisites changes the rule with it, and every
other template's ``requires`` stops being decoration.

One prerequisite cannot be expressed as "another capability exists": the merge
queue's integration gate runs the declared CI workflow's ``merge_group``
trigger, and a workflow without that trigger leaves the queue with nothing to
run, so a queued pull request never merges. That check lives here beside the
generic one, reads the workflow through the shared inspector, and refuses only
when the workflow is readable and the trigger is provably absent.

Creation is the boundary. An existing row is the project's recorded state and
is not re-litigated on every settings edit; what this refuses is minting a
declaration the project cannot honor.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.db_optional_queries import fetch_optional_rows
from yoke_core.domain.github_actions_workflow_inspection import (
    WORKFLOWS_DIRECTORY,
    declares_merge_group,
    workflow_path,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
    MERGE_QUEUE_CAPABILITY_TYPE,
)


class CapabilityPrerequisiteError(ValueError):
    """A capability cannot be declared because a prerequisite is missing."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def declared_prerequisites(conn: Any, cap_type: str) -> list[str]:
    """The capability types a template says must already be declared.

    The template table is optional: a minimal or partially-migrated database
    can carry `project_capabilities` without it. A control plane that cannot
    read the declaration knows of no prerequisites, which is the same answer
    as a template that declares none — and is emphatically not a reason to
    fail the write it was asked to guard.
    """
    rows = fetch_optional_rows(
        conn,
        f"SELECT requires FROM capability_templates WHERE id={_p(conn)}",
        (cap_type,),
        savepoint="_yoke_capability_template_requires_probe",
    )
    raw = rows[0][0] if rows else None
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(entry) for entry in parsed if str(entry).strip()]


def _declared_types(conn: Any, project_id: int) -> set[str]:
    rows = fetch_optional_rows(
        conn,
        f"SELECT type FROM project_capabilities WHERE project_id={_p(conn)}",
        (int(project_id),),
        savepoint="_yoke_project_capability_types_probe",
    )
    return {str(row[0]) for row in rows}


def _declared_workflow_file(conn: Any, project_id: int) -> str:
    row = query_one(
        conn,
        "SELECT COALESCE(settings, '{}') AS settings FROM project_capabilities "
        f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
        (int(project_id), CI_WORKFLOW_CAPABILITY_TYPE),
    )
    if row is None:
        return ""
    try:
        settings = json.loads(str(row["settings"] or "{}"))
    except (TypeError, ValueError):
        return ""
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("workflow_file") or "").strip()


def _require_merge_group_trigger(
    conn: Any, *, project_id: int, project: str,
) -> None:
    """Refuse a merge-queue declaration whose workflow has no merge_group."""
    workflow_file = _declared_workflow_file(conn, int(project_id))
    if not workflow_file:
        raise CapabilityPrerequisiteError(
            f"project {project!r} declares '{CI_WORKFLOW_CAPABILITY_TYPE}' "
            f"with no workflow_file, so the merge queue has no workflow to run "
            f"its merge_group gate. Name the workflow first with "
            f"`yoke projects capability-settings set --project {project} "
            f"--cap-type {CI_WORKFLOW_CAPABILITY_TYPE} --new "
            f"--settings-json '{{\"workflow_file\":\"<name>.yml\"}}'`."
        )
    checkout = checkout_for_project_id(int(project_id))
    if checkout is None:
        return
    path = workflow_path(checkout, workflow_file)
    if not path.is_file():
        raise CapabilityPrerequisiteError(
            f"project {project!r} declares {WORKFLOWS_DIRECTORY}/"
            f"{workflow_file}, but that file does not exist in {checkout}, so "
            f"the merge queue's merge_group gate cannot be verified. Fix the "
            f"'{CI_WORKFLOW_CAPABILITY_TYPE}' declaration first."
        )
    if not declares_merge_group(path.read_text(encoding="utf-8")):
        raise CapabilityPrerequisiteError(
            f"{WORKFLOWS_DIRECTORY}/{workflow_file} declares no `merge_group` "
            f"trigger, so the merge queue's integration gate would have nothing "
            f"to run and a queued pull request would never merge. Add "
            f"`merge_group:` to that workflow's `on` triggers before declaring "
            f"'{MERGE_QUEUE_CAPABILITY_TYPE}' on project {project!r}."
        )


def require_prerequisites(
    conn: Any,
    *,
    project_id: int,
    project: str,
    cap_type: str,
) -> None:
    """Refuse creating ``cap_type`` while its prerequisites are unmet."""
    required = declared_prerequisites(conn, cap_type)
    if required:
        declared = _declared_types(conn, int(project_id))
        missing = [name for name in required if name not in declared]
        if missing:
            plural = len(missing) > 1
            raise CapabilityPrerequisiteError(
                f"capability {cap_type!r} requires {', '.join(missing)} on "
                f"project {project!r}, and "
                f"{'those are' if plural else 'that is'} not declared. Declare "
                f"{'them' if plural else 'it'} first, then declare "
                f"{cap_type!r}."
            )
    if cap_type == MERGE_QUEUE_CAPABILITY_TYPE:
        _require_merge_group_trigger(
            conn, project_id=int(project_id), project=project,
        )


__all__ = [
    "CapabilityPrerequisiteError",
    "declared_prerequisites",
    "require_prerequisites",
]
