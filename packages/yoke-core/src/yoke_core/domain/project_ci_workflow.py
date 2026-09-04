"""Connected-control-plane read for a project's required CI workflow."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)


def project_ci_workflow_settings(project: str) -> dict:
    """Return the ``ci_workflow_file`` settings document, or ``{}`` when undeclared."""
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "cap_type": CI_WORKFLOW_CAPABILITY_TYPE,
        },
    )
    if not response.success:
        code = (response.error.code if response.error else "unknown") or "unknown"
        if code == "not_found":
            return {}
        message = (response.error.message if response.error else "") or "read failed"
        raise RuntimeError(f"CI workflow capability read failed ({code}): {message}")
    raw = str((response.result or {}).get("settings_json") or "{}")
    try:
        settings = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("CI workflow capability returned invalid JSON") from exc
    if not isinstance(settings, dict):
        raise RuntimeError("CI workflow capability must be a JSON object")
    return settings


def project_ci_workflow_file(project: str) -> str:
    """Return the declared workflow filename, or empty when undeclared."""
    return str(project_ci_workflow_settings(project).get("workflow_file") or "").strip()


__all__ = ["project_ci_workflow_file", "project_ci_workflow_settings"]
