"""Execute a narrow Pulumi operator command from stack-scoped authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import sys
import tempfile
from typing import Any, TextIO

from yoke_core.domain.deploy_remote import (
    aws_machine_capability_env,
)
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    load_project_renderer_settings,
)
from yoke_core.domain.projects_pulumi_state_checkpoint_import import (
    import_checkpoint_state,
)
from yoke_core.tools.pulumi_exec_authority import (
    authority_env as _authority_env,
)
from yoke_core.tools.pulumi_exec_files import (
    new_owner_only_output as _new_owner_only_output,
    write_owner_only as _write_owner_only,
)
from yoke_core.tools.pulumi_exec_validation import validated_command
from yoke_core.tools.pulumi_exec_types import PulumiExecError
from yoke_core.tools.runner_fleet_redacted_process import run_redacted_child
from yoke_core.tools.runner_fleet_exec import resolve_local_runner_fleet_github_auth


def execute_pulumi_command(
    project: str,
    stack: str,
    command: Sequence[str],
    *,
    config_loader: Callable[[str, str], Mapping[str, Any]],
    project_root: Path,
    aws_env_loader: Callable[..., Mapping[str, str]] = aws_machine_capability_env,
    github_auth_loader: Callable[..., Any] = resolve_project_github_auth,
    bootstrap_local_authority: bool = False,
    local_github_auth_loader: Callable[..., Any] = (
        resolve_local_runner_fleet_github_auth
    ),
    settings_loader: Callable[[str], ProjectRendererSettings] = (
        load_project_renderer_settings
    ),
    state_importer: Callable[..., Mapping[str, Any]] = import_checkpoint_state,
    child_factory: Callable[..., Any] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Materialize one stack and run a bounded operator operation."""
    selected_project = str(project or "").strip()
    selected_stack = str(stack or "").strip()
    if not selected_project or not selected_stack:
        raise PulumiExecError("project and stack are required")
    if command and str(command[0]) == "init":
        from yoke_core.tools.pulumi_exec_init import execute_pulumi_stack_init

        return execute_pulumi_stack_init(
            selected_project,
            selected_stack,
            command,
            project_root=project_root,
            settings_loader=settings_loader,
            state_importer=state_importer,
            aws_env_loader=aws_env_loader,
            child_factory=child_factory,
            out=out,
            err=err,
        )
    argv, json_output = validated_command(selected_stack, command)
    payload = dict(config_loader(selected_project, selected_stack))
    _verify_payload_identity(payload, selected_project, selected_stack)
    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        raise PulumiExecError("Pulumi stack authority is missing")

    with tempfile.TemporaryDirectory(prefix="yoke-pulumi-exec-") as raw_temp:
        temp_root = Path(raw_temp)
        temp_root.chmod(0o700)
        config_path = temp_root / "stack-config.json"
        _write_owner_only(config_path, payload)
        render_root = temp_root / "render"
        render_scoped_pulumi_config(
            payload, project_root=project_root, output_dir=render_root
        )
        child_env, redaction_terms = _authority_env(
            selected_project,
            authority,
            payload,
            aws_env_loader=aws_env_loader,
            github_auth_loader=github_auth_loader,
            bootstrap_local_authority=bootstrap_local_authority,
            local_github_auth_loader=local_github_auth_loader,
        )
        child_out = out or sys.stdout
        json_handle = None
        try:
            if json_output is not None:
                json_handle = _new_owner_only_output(json_output)
                child_out = json_handle
            kwargs: dict[str, Any] = {
                "env": child_env,
                "redaction_terms": redaction_terms,
                "out": child_out,
                "err": err or sys.stderr,
                "cwd": render_root / "infra",
            }
            if child_factory is not None:
                kwargs["child_factory"] = child_factory
            result = run_redacted_child(argv, **kwargs)
            return result.returncode
        finally:
            if json_handle is not None:
                json_handle.close()


def _verify_payload_identity(
    payload: Mapping[str, Any], project: str, stack: str
) -> None:
    if payload.get("config_schema") != 2:
        raise PulumiExecError("Pulumi stack config schema must be 2")
    if payload.get("project_slug") != project or payload.get("stack_name") != stack:
        raise PulumiExecError(
            "Pulumi stack config identity does not match the requested project/stack"
        )


__all__ = ["PulumiExecError", "execute_pulumi_command"]
