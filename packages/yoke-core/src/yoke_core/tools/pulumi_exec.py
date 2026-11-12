"""Execute a narrow Pulumi operator command from stack-scoped authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import sys
import tempfile
import yaml
from typing import Any, TextIO

from yoke_core.domain import yaml_helper
from yoke_core.domain.deploy_remote import (
    aws_machine_capability_env,
)
from yoke_core.domain.project_github_auth import resolve_project_github_auth
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
from yoke_core.tools.pulumi_exec_authority import (
    authority_env as _authority_env,
)
from yoke_core.tools.pulumi_exec_destroy import (
    destructive_operation,
    refuse_consumed_vps_stack,
    require_destroy_confirmation,
)
from yoke_core.tools.pulumi_exec_files import (
    new_owner_only_output as _new_owner_only_output,
)
from yoke_core.tools.pulumi_exec_file_backed import (
    require_stack_file,
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
    confirm_destroy: str | None = None,
    child_factory: Callable[..., Any] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run a bounded operator operation on one checked-in stack.

    The stack runs from a copy of the project's ``infra/`` directory with
    Yoke-owned ``yoke:`` values added to the copied
    ``infra/Pulumi.<stack>.yaml`` (see ``pulumi_exec_file_backed``). A stack
    without that file is refused with the recovery step.

    ``caller_root`` is the git top-level the operator invoked from. Every
    operation states the tree it renders before producing any result, and a
    caller standing in a different working tree of that same repository is
    refused instead of handed a summary for a tree they did not name.

    ``destroy`` and ``stack rm`` require ``confirm_destroy`` to name the
    exact stack. A read-only ``destroy --preview-only`` needs no confirmation.
    """
    selected_project = str(project or "").strip()
    selected_stack = str(stack or "").strip()
    if not selected_project or not selected_stack:
        raise PulumiExecError("project and stack are required")
    announce_render_source(project_root, caller_root=caller_root, err=err or sys.stderr)
    stack_file = require_stack_file(project_root, selected_stack)
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
            aws_env_loader=aws_env_loader,
            child_factory=child_factory,
            out=out,
            err=err,
        )
    argv, json_output = validated_command(selected_stack, command)
    operation = destructive_operation(argv)
    confirmation_operation = None if "--preview-only" in argv else operation
    require_destroy_confirmation(selected_stack, confirmation_operation, confirm_destroy)
    settings = settings_loader(selected_project)
    if settings.project != selected_project:
        raise PulumiExecError(
            "Pulumi project settings do not match the requested project"
        )
    if operation is not None:
        verdict = refuse_consumed_vps_stack(
            selected_project, selected_stack, settings, project_root
        )
        (err or sys.stderr).write(f"{verdict}\n")
    payload, authority, runner_fleet = _file_backed_inputs(
        selected_project, selected_stack, stack_file, settings
    )

    with tempfile.TemporaryDirectory(prefix="yoke-pulumi-exec-") as raw_temp:
        temp_root = Path(raw_temp)
        temp_root.chmod(0o700)
        render_root = temp_root / "render"
        infra_root = stage_file_backed_infra(
            project_root,
            selected_stack,
            render_root,
            payload["render_values"],
        )
        if any(arg == "--target" or arg.startswith("--target=") for arg in argv):
            # stage_file_backed_infra already refused unparseable YAML.
            declaration = yaml.safe_load((infra_root / "Pulumi.yaml").read_text())
            project_name = (
                declaration.get("name") if isinstance(declaration, Mapping) else None
            )
            if not isinstance(project_name, str) or not project_name.strip():
                raise PulumiExecError(
                    "pulumi_target_project_missing: infra/Pulumi.yaml must declare name; repair the project declaration and retry"
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
        "stack_secrets": _stack_file_secrets(stack_file),
    }
    return payload, authority, github_access == RUNNER_FLEET_ACCESS


def _stack_file_secrets(stack_file: Path) -> tuple[str, ...]:
    """The stack file's encrypted data key, redacted from child output."""
    declared = yaml_helper.read_top_level_scalars(stack_file, ("encryptedkey",))
    key = str(declared.get("encryptedkey") or "").strip()
    return (key,) if key else ()


__all__ = ["PulumiExecError", "execute_pulumi_command"]
