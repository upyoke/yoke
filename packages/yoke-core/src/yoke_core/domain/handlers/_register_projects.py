"""Handler registrations for project-write functions (projects.create/update).

Split out of :mod:`_register_qa_reads` so that module stays under the
authored-file line cap. Both surfaces are backed by the idempotent project
upsert workhorse and differ only in authorization scope — ``projects.create``
is org-scoped (register a new project), ``projects.update`` is project-scoped
(edit an existing one); see ``function_authz_scope``. (The project *read*
registrations still live in ``_register_qa_reads``.)
"""
from __future__ import annotations

from yoke_core.domain.handlers import projects_upsert as _projects_upsert

_PROJECT_WRITE_SURFACES = (
    ("projects.create", _projects_upsert.handle_projects_create),
    ("projects.update", _projects_upsert.handle_projects_update),
)


def register(registry) -> None:
    """Register projects.create + projects.update via the given registry module."""
    for function_id, handler in _PROJECT_WRITE_SURFACES:
        registry.register(
            function_id, handler,
            _projects_upsert.ProjectsUpsertRequest,
            _projects_upsert.ProjectsUpsertResponse,
            stability="stable",
            owner_module="yoke_core.domain.handlers.projects_upsert",
            target_kinds=["global"],
            side_effects=["projects_upsert", "project_capabilities_insert"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[], adapter_status="live", claim_required_kind=None,
            ambient_session_required=False,
        )
