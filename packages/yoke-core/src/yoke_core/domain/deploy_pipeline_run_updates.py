"""In-process deployment-run bookkeeping for the deploy pipeline."""

from __future__ import annotations

from yoke_core.domain import deployment_runs_crud_mutate


class DeployPipelineRunUpdateError(RuntimeError):
    """A deployment-run bookkeeping write did not land."""


def update_run_field(run_id: str, field: str, value: str) -> None:
    """Apply the registered run update mutation without spawning a helper."""
    try:
        error = deployment_runs_crud_mutate.cmd_update(run_id, field, value)
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise DeployPipelineRunUpdateError(
            f"deployment run bookkeeping write failed for {run_id} "
            f"({field}={value}): {detail}; restore the selected db-admin "
            f"connection, then re-drive {run_id}"
        ) from exc
    if error:
        raise DeployPipelineRunUpdateError(
            f"deployment run bookkeeping write was refused for {run_id} "
            f"({field}={value}): {error}; repair the named condition, then "
            f"re-drive {run_id}"
        )


__all__ = ["DeployPipelineRunUpdateError", "update_run_field"]
