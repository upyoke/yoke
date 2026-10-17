"""Resolve relay jobs to a recorded session workspace or project checkout."""

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config


class RelayJobSurfaceError(ValueError):
    """A working-directory refusal carrying the result code for the relay wire."""

    def __init__(self, result_code: str, message: str) -> None:
        super().__init__(message)
        self.result_code = result_code


def checkout_for_project(project_id: int) -> Path | None:
    for configured in machine_config.configured_projects(existing_only=True):
        if configured.project_id == project_id:
            return configured.checkout
    return None


def working_directory(job: Mapping[str, Any], project_id: int | None) -> Path:
    """Session workspace wins because native transcripts are keyed by that path."""
    workspace = str(job.get("target_workspace") or "").strip()
    if workspace:
        candidate = Path(workspace)
        if not candidate.is_dir():
            raise RelayJobSurfaceError(
                "session_workspace_missing",
                "target session workspace is not a directory on this machine: "
                f"{workspace} — restore that directory, or terminate the "
                "session deliberately if its lane is gone",
            )
        return candidate
    if project_id is None:
        raise RelayJobSurfaceError(
            "session_workspace_unrecorded",
            "org-scoped session has no recorded workspace on this machine — "
            "terminate it deliberately (confirm the command with `yoke sessions --help`) "
            "or start a new session; project registration does not apply",
        )
    checkout = checkout_for_project(project_id)
    if checkout is None:
        raise RelayJobSurfaceError(
            "checkout_unavailable",
            "relay job project has no registered checkout — register it with "
            "`yoke project register <checkout> --project-id <id>`",
        )
    return checkout


__all__ = ["RelayJobSurfaceError", "checkout_for_project", "working_directory"]
