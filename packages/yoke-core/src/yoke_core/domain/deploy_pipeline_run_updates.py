"""In-process deployment-run bookkeeping for the deploy pipeline."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import deploy_pipeline_control_plane
from yoke_core.domain.deployment_start_timing import timed_call

_MAX_START_RETRIES = 3
_STALE_ATTESTATION = "candidate_containment_attestation_stale"


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
    """Attest and start; refresh a stale basis at most three times."""
    try:
        for attempt in range(_MAX_START_RETRIES + 1):
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

                attestation = timed_call(
                    "containment_attestation",
                    attest_candidate_containment,
                    basis,
                    _checkout,
                )
            try:
                timed_call(
                    "executing_transition",
                    deploy_pipeline_control_plane.update_run_field,
                    run_id,
                    "status",
                    "executing",
                    candidate_containment=attestation,
                )
                return
            except deploy_pipeline_control_plane.DeploymentControlPlaneError as exc:
                if exc.code != _STALE_ATTESTATION or attempt == _MAX_START_RETRIES:
                    raise
                print(
                    f"Run {run_id}: {_STALE_ATTESTATION}; retry "
                    f"{attempt + 1}/{_MAX_START_RETRIES} with a fresh containment basis"
                )
                basis = timed_call(
                    "containment_basis_refresh",
                    deploy_pipeline_control_plane.containment_basis,
                    run_id,
                )
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise DeployPipelineRunUpdateError(
            f"deployment run start failed for {run_id}: {detail}; repair the "
            f"named containment source or control-plane connection, then re-drive "
            f"{run_id}"
        ) from exc


__all__ = ["DeployPipelineRunUpdateError", "start_run", "update_run_field"]
