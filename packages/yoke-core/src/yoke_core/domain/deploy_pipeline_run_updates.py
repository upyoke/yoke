"""In-process deployment-run bookkeeping for the deploy pipeline."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import deploy_pipeline_control_plane


class DeployPipelineRunUpdateError(RuntimeError):
    """A deployment-run bookkeeping write did not land."""


def update_run_field(run_id: str, field: str, value: str) -> None:
    """Apply the registered run update mutation without spawning a helper."""
    try:
        deploy_pipeline_control_plane.update_run_field(run_id, field, value)
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise DeployPipelineRunUpdateError(
            f"deployment run bookkeeping write failed for {run_id} "
            f"({field}={value}): {detail}; restore the selected control-plane "
            f"connection, then re-drive {run_id}"
        ) from exc


def start_run(
    run_id: str,
    basis: Any,
    primary_checkout: str,
) -> None:
    """Attest candidate containment locally and atomically start the run."""
    try:
        attestation = None
        if isinstance(basis, Mapping):
            from yoke_core.domain.deployment_run_contained_items import (
                attest_candidate_containment,
            )
            from yoke_core.domain.project_checkout_locations import (
                checkout_for_project_slug,
            )

            primary_project = str(basis.get("primary_project") or "")

            def _checkout(project: str) -> str:
                if primary_checkout and project == primary_project:
                    return primary_checkout
                found = checkout_for_project_slug(project)
                return str(found) if found is not None else ""

            attestation = attest_candidate_containment(basis, _checkout)
        deploy_pipeline_control_plane.update_run_field(
            run_id,
            "status",
            "executing",
            candidate_containment=attestation,
        )
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise DeployPipelineRunUpdateError(
            f"deployment run start failed for {run_id}: {detail}; repair the "
            f"named containment source or control-plane connection, then re-drive "
            f"{run_id}"
        ) from exc


__all__ = ["DeployPipelineRunUpdateError", "start_run", "update_run_field"]
