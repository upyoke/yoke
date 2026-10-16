"""Transport-aware facts and local Git helper access for merge audits."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_contracts.project_defaults import default_project_for_directory


def load_snapshot(epic_filter: str | None, *, project: str | None = None) -> dict:
    """Relay DB facts; Git and filesystem evidence stays on this machine."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    project = (
        project
        or os.environ.get("YOKE_PROJECT")
        or default_project_for_directory(Path.cwd())
    )
    if epic_filter is None:
        target = TargetRef(kind="global", project_id=project)
    else:
        target = TargetRef(kind="item", public_ref=epic_filter, project_id=project)
    response = call_dispatcher(
        function_id="merge.audit.snapshot", target=target, payload={}
    )
    if not response.success:
        error = response.error
        raise RuntimeError(
            f"merge_audit_snapshot_unavailable: {error.code if error else 'unknown'}: "
            f"{error.message if error else 'snapshot refused'}. "
            f"{error.recovery_hint if error and error.recovery_hint else 'Pass --project P; if the function is not served, ask the control-plane operator to serve the carrying release, then retry yoke merge audit.'}"
        )
    return response.result or {}


def _parent():
    from yoke_core.engines import merge_audit as _ma

    return _ma
