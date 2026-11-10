"""Execute a narrow Pulumi operator command from stack-scoped authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import sys
import tempfile
import yaml
from typing import Any, TextIO

from yoke_core.domain.deploy_remote import (
    aws_machine_capability_env,
)
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain.project_renderer_pulumi_imports import (
    RenderedProgramIncomplete,
)
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    load_project_renderer_settings,
)
from yoke_core.domain.pulumi_file_stack_values import (
    RUNNER_FLEET_ACCESS,
    FileStackValuesError,
    file_stack_authority,
    file_stack_yoke_values,
)
from yoke_core.domain.projects_pulumi_state_checkpoint_import import (
    import_checkpoint_state,
)
from yoke_core.domain.projects_pulumi_state_stack_remove import (
    remove_stack_state,
)
from yoke_core.tools.pulumi_exec_authority import (
    authority_env as _authority_env,
)
from yoke_core.tools.pulumi_exec_destroy import (
    STACK_RM,
    clear_removed_stack_state,
    destructive_operation,
    refuse_consumed_vps_stack,
    require_destroy_confirmation,
)
from yoke_core.tools.pulumi_exec_files import (
    new_owner_only_output as _new_owner_only_output,
    write_owner_only as _write_owner_only,
)
from yoke_core.tools.pulumi_exec_file_backed import (
    file_backed_stack_path,
    file_stack_github_access,
    stage_file_backed_infra,
)
from yoke_core.tools.pulumi_exec_github_failure import (
    CaptureTee,
    named_github_provider_failure,
)
from yoke_core.tools.pulumi_exec_source import announce_render_source
from yoke_core.tools.pulumi_exec_validation import (
    validated_command,
    validate_target_project,
)
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
    caller_root: Path | None = None,
    aws_env_loader: Callable[..., Mapping[str, str]] = aws_machine_capability_env,
    github_auth_loader: Callable[..., Any] = resolve_project_github_auth,
    hosted_repository_token_loader: Callable[[str, str, Mapping[str, str]], str]
    | None = None,
    bootstrap_local_authority: bool = False,
    local_github_auth_loader: Callable[..., Any] = (
        resolve_local_runner_fleet_github_auth
    ),
    settings_loader: Callable[[str], ProjectRendererSettings] = (
        load_project_renderer_settings
    ),
    state_importer: Callable[..., Mapping[str, Any]] = import_checkpoint_state,
    confirm_destroy: str | None = None,
    stack_state_remover: Callable[..., Mapping[str, Any]] = remove_stack_state,
    child_factory: Callable[..., Any] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Materialize one stack and run a bounded operator operation.

    A stack with a checked-in ``infra/Pulumi.<stack>.yaml`` runs from a copy
    of that file plus Yoke-owned ``yoke:`` values (see
    ``pulumi_exec_file_backed``); any other stack is rendered from the
    project's templates and server-built config.

    ``caller_root`` is the git top-level the operator invoked from. Every
    operation states the tree it renders before producing any result, and a
    caller standing in a different working tree of that same repository is
    refused instead of handed a summary for a tree they did not name.

    ``destroy`` and ``stack rm`` require ``confirm_destroy`` to name the
    exact stack; a successful ``stack rm`` also drops its operator state.
    """
    selected_project = str(project or "").strip()
    selected_stack = str(stack or "").strip()
    if not selected_project or not selected_stack:
        raise PulumiExecError("project and stack are required")
    announce_render_source(project_root, caller_root=caller_root, err=err or sys.stderr)
    stack_file = file_backed_stack_path(project_root, selected_stack)
    if command and str(command[0]) == "init":
        require_destroy_confirmation(selected_stack, None, confirm_destroy)
        from yoke_core.tools.pulumi_exec_init import execute_pulumi_stack_init

        return execute_pulumi_stack_init(
            selected_project,
            selected_stack,
            command,
            project_root=project_root,
            stack_file=stack_file,
            settings_loader=settings_loader,
            state_importer=state_importer,
            aws_env_loader=aws_env_loader,
            child_factory=child_factory,
            out=out,
            err=err,
        )
    argv, json_output = validated_command(selected_stack, command)
    operation = destructive_operation(argv)
    require_destroy_confirmation(selected_stack, operation, confirm_destroy)
    settings = None
    if operation is not None or stack_file is not None:
        settings = settings_loader(selected_project)
        if settings.project != selected_project:
            raise PulumiExecError(
                "Pulumi renderer settings do not match the requested project"
            )
    if operation is not None:
        refuse_consumed_vps_stack(selected_project, selected_stack, settings)
    if stack_file is not None:
        payload, authority, runner_fleet = _file_backed_inputs(
            selected_project, selected_stack, stack_file, settings
        )
    else:
        payload = dict(config_loader(selected_project, selected_stack))
        _verify_payload_identity(payload, selected_project, selected_stack)
        authority = payload.get("authority")
        if not isinstance(authority, Mapping):
            raise PulumiExecError("Pulumi stack authority is missing")
        runner_fleet = payload.get("stack_kind") == "runner-fleet"

    with tempfile.TemporaryDirectory(prefix="yoke-pulumi-exec-") as raw_temp:
        temp_root = Path(raw_temp)
        temp_root.chmod(0o700)
        render_root = temp_root / "render"
        if stack_file is not None:
            infra_root = stage_file_backed_infra(
                project_root,
                selected_stack,
                render_root,
                payload["render_values"],
            )
        else:
            _write_owner_only(temp_root / "stack-config.json", payload)
            try:
                render_scoped_pulumi_config(
                    payload, project_root=project_root, output_dir=render_root
                )
            except RenderedProgramIncomplete as exc:
                raise PulumiExecError(str(exc)) from exc
            infra_root = render_root / "infra"
        if any(arg == "--target" or arg.startswith("--target=") for arg in argv):
            try:
                declaration = yaml.safe_load(
                    (infra_root / "Pulumi.yaml").read_text()
                )
            except yaml.YAMLError as exc:
                raise PulumiExecError(
                    "pulumi_target_project_invalid: rendered Pulumi.yaml is invalid YAML; repair the project declaration and retry"
                ) from exc
            project_name = (
                declaration.get("name") if isinstance(declaration, Mapping) else None
            )
            if not isinstance(project_name, str) or not project_name.strip():
                raise PulumiExecError(
                    "pulumi_target_project_missing: rendered Pulumi.yaml must declare name; repair the project declaration and retry"
                )
            validate_target_project(argv, selected_stack, project_name)
        child_env, redaction_terms = _authority_env(
            selected_project,
            authority,
            payload,
            aws_env_loader=aws_env_loader,
            github_auth_loader=github_auth_loader,
            hosted_repository_token_loader=hosted_repository_token_loader,
            bootstrap_local_authority=bootstrap_local_authority,
            local_github_auth_loader=local_github_auth_loader,
            runner_fleet=runner_fleet,
        )
        child_out = out or sys.stdout
        child_err = CaptureTee(err or sys.stderr)
        json_handle = None
        try:
            if json_output is not None:
                json_handle = _new_owner_only_output(json_output)
                child_out = json_handle
            kwargs: dict[str, Any] = {
                "env": child_env,
                "redaction_terms": redaction_terms,
                "out": child_out,
                "err": child_err,
                "cwd": infra_root,
            }
            if child_factory is not None:
                kwargs["child_factory"] = child_factory
            result = run_redacted_child(argv, **kwargs)
            if result.returncode:
                named = named_github_provider_failure(
                    selected_project, child_err.getvalue()
                )
                if named:
                    raise PulumiExecError(named)
            elif operation == STACK_RM:
                clear_removed_stack_state(
                    selected_project,
                    selected_stack,
                    stack_state_remover,
                    out or sys.stdout,
                )
            return result.returncode
        finally:
            if json_handle is not None:
                json_handle.close()


def _file_backed_inputs(
    project: str, stack: str, stack_file: Path, settings: ProjectRendererSettings
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Yoke-owned values and authority for a stack run from its own file."""
    github_access = file_stack_github_access(stack_file)
    try:
        values = file_stack_yoke_values(settings, stack, github_access)
        authority = file_stack_authority(settings, values, github_access)
    except FileStackValuesError as exc:
        raise PulumiExecError(str(exc)) from exc
    payload = {
        "project_slug": project,
        "stack_name": stack,
        "render_values": values,
        "operator_state": {},
    }
    return payload, authority, github_access == RUNNER_FLEET_ACCESS


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
