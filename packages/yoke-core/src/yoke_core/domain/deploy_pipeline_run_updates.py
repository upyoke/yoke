"""In-process deployment-run bookkeeping for the deploy pipeline."""

from __future__ import annotations

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


__all__ = ["DeployPipelineRunUpdateError", "update_run_field"]
