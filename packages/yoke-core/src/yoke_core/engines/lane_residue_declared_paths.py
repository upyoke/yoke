"""Project-declared disposable generated paths, read for lane-residue clearing.

One relay call resolves the paths a project has declared through its
``project-policy`` capability (key ``disposable_generated_paths``), for the
shared residue policy in ``merge_worktree_cleanliness`` to treat as
disposable alongside its built-in cache names. Every caller already knows
its own project (``MergeContext.project``, or a checkout it can map through
the machine's checkout-to-project registry); resolution here always goes
through ``projects.capability_settings.get`` so it works over the same
local or relayed transport the rest of this engine already uses, and it
fails closed — an unreachable control plane or an invalid stored
declaration reads as no additional declarations, never as a crash or a
widened default.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_contract.disposable_generated_paths_policy import (
    parsed_disposable_generated_paths,
)
from yoke_contracts.project_defaults import default_project_for_directory

from yoke_core.domain import json_helper
from yoke_core.domain.project_attribution import resolved_project


def declared_disposable_roots_for_project(
    project: str | None,
) -> frozenset[PurePosixPath]:
    """*project*'s declared additional disposable path roots."""
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    named = resolved_project(project)
    if not named:
        return frozenset()
    try:
        response = call_dispatcher(
            function_id="projects.capability_settings.get",
            target=TargetRef(kind="global"),
            payload={
                "project": named,
                "cap_type": "project-policy",
            },
        )
    except Exception:  # noqa: BLE001 - unreachable authority == no declarations
        return frozenset()
    if not response.success:
        return frozenset()
    settings_json = str((response.result or {}).get("settings_json") or "")
    if not settings_json:
        return frozenset()
    try:
        settings = json_helper.loads_text(settings_json)
    except Exception:  # noqa: BLE001 - unreadable document == no declarations
        return frozenset()
    if not isinstance(settings, dict):
        return frozenset()
    declared = parsed_disposable_generated_paths(
        settings.get("disposable_generated_paths", [])
    )
    return frozenset(PurePosixPath(entry) for entry in declared)


def declared_disposable_roots(repo_root: str | Path) -> frozenset[PurePosixPath]:
    """Declared roots for the project *repo_root* belongs to on this machine."""
    return declared_disposable_roots_for_project(
        default_project_for_directory(repo_root)
    )


__all__ = [
    "declared_disposable_roots",
    "declared_disposable_roots_for_project",
]
