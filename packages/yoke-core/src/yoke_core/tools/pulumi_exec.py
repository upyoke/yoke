"""Execute a narrow Pulumi operator command from stack-scoped authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, TextIO

from yoke_core.domain.deploy_remote import aws_machine_capability_env
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.tools.runner_fleet_redacted_process import run_redacted_child


_ALLOWED_COMMANDS = frozenset({"preview", "refresh", "import"})
_IMPORT_FLAGS = frozenset({
    "--protect=false", "--generate-code=false", "--yes",
    "--non-interactive",
})
_PREVIEW_FLAGS = frozenset({
    "--diff", "--expect-no-changes", "--non-interactive", "--refresh",
    "--suppress-outputs",
})
_REFRESH_FLAGS = frozenset({
    "--non-interactive", "--preview-only", "--skip-preview", "--yes",
})
_AMBIENT_GITHUB_ENV = frozenset({
    "GH_ENTERPRISE_TOKEN", "GH_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
    "GITHUB_TOKEN", "RUNNER_FLEET_GITHUB_TOKEN",
})


class PulumiExecError(RuntimeError):
    """The requested local Pulumi operation is outside the safe boundary."""


def execute_pulumi_command(
    project: str,
    stack: str,
    command: Sequence[str],
    *,
    config_loader: Callable[[str, str], Mapping[str, Any]],
    project_root: Path,
    aws_env_loader: Callable[..., Mapping[str, str]] = aws_machine_capability_env,
    github_auth_loader: Callable[..., Any] = resolve_project_github_auth,
    child_factory: Callable[..., Any] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Materialize one stack and run preview, refresh, or file import."""
    selected_project = str(project or "").strip()
    selected_stack = str(stack or "").strip()
    if not selected_project or not selected_stack:
        raise PulumiExecError("project and stack are required")
    argv, json_output = _validated_command(selected_stack, command)
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


def _validated_command(
    stack: str, command: Sequence[str]
) -> tuple[list[str], Path | None]:
    parts = [str(part) for part in command]
    if not parts or parts[0] not in _ALLOWED_COMMANDS:
        raise PulumiExecError(
            "Pulumi exec allows only preview, refresh, and import"
        )
    operation = parts[0]
    args = parts[1:]
    _assert_stack_flag(args, stack)
    json_output: Path | None = None
    if operation == "import":
        _validate_import_args(args)
        args = _absolute_option_path(args, "--file")
    elif operation == "preview":
        args, json_output = _preview_output_args(args)
        _validate_flag_args(args, _PREVIEW_FLAGS, path_options={"--import-file"})
        args = _absolute_option_path(args, "--import-file")
        if json_output is not None:
            args.append("--json")
    else:
        _validate_flag_args(args, _REFRESH_FLAGS)
    args = _without_stack_flag(args)
    return ["pulumi", operation, *args, "--stack", stack], json_output


def _assert_stack_flag(args: Sequence[str], stack: str) -> None:
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            if index + 1 >= len(args) or args[index + 1] != stack:
                raise PulumiExecError("child --stack must match the requested stack")
            index += 2
            continue
        if value.startswith("--stack=") and value.split("=", 1)[1] != stack:
            raise PulumiExecError("child --stack must match the requested stack")
        index += 1


def _without_stack_flag(args: Sequence[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            index += 2
        elif value.startswith("--stack="):
            index += 1
        else:
            result.append(value)
            index += 1
    return result


def _validate_import_args(args: Sequence[str]) -> None:
    normalized: list[str] = []
    index = 0
    file_count = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            index += 2
            continue
        if value.startswith("--stack="):
            index += 1
            continue
        if value == "--file":
            if index + 1 >= len(args):
                raise PulumiExecError("pulumi import --file requires a path")
            file_count += 1
            normalized.extend((value, args[index + 1]))
            index += 2
            continue
        if value in _IMPORT_FLAGS:
            normalized.append(value)
            index += 1
            continue
        raise PulumiExecError(f"pulumi import argument is not allowed: {value}")
    if file_count != 1:
        raise PulumiExecError("pulumi import requires exactly one --file")


def _validate_flag_args(
    args: Sequence[str],
    allowed_flags: frozenset[str],
    *,
    path_options: frozenset[str] | set[str] = frozenset(),
) -> None:
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            index += 2
            continue
        if value.startswith("--stack="):
            index += 1
            continue
        if value in path_options:
            if index + 1 >= len(args):
                raise PulumiExecError(f"{value} requires a path")
            index += 2
            continue
        if any(value.startswith(f"{option}=") for option in path_options):
            index += 1
            continue
        if value not in allowed_flags:
            raise PulumiExecError(
                f"Pulumi argument is not allowed for this operation: {value}"
            )
        index += 1


def _preview_output_args(args: Sequence[str]) -> tuple[list[str], Path | None]:
    result: list[str] = []
    output: Path | None = None
    index = 0
    while index < len(args):
        if args[index] == "--json-output":
            if output is not None or index + 1 >= len(args):
                raise PulumiExecError("--json-output requires one unique path")
            output = Path(args[index + 1]).expanduser().resolve()
            index += 2
        else:
            result.append(args[index])
            index += 1
    return result, output


def _absolute_option_path(args: Sequence[str], option: str) -> list[str]:
    result = list(args)
    for index, value in enumerate(result):
        if value == option:
            if index + 1 >= len(result):
                raise PulumiExecError(f"{option} requires a path")
            result[index + 1] = str(Path(result[index + 1]).expanduser().resolve())
        elif value.startswith(f"{option}="):
            result[index] = f"{option}={Path(value.split('=', 1)[1]).expanduser().resolve()}"
    return result


def _verify_payload_identity(
    payload: Mapping[str, Any], project: str, stack: str
) -> None:
    if payload.get("config_schema") != 2:
        raise PulumiExecError("Pulumi stack config schema must be 2")
    if payload.get("project_slug") != project or payload.get("stack_name") != stack:
        raise PulumiExecError(
            "Pulumi stack config identity does not match the requested project/stack"
        )


def _authority_env(
    project: str,
    authority: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    aws_env_loader: Callable[..., Mapping[str, str]],
    github_auth_loader: Callable[..., Any],
) -> tuple[dict[str, str], tuple[str, ...]]:
    capability = str(authority.get("aws_capability") or "").strip()
    region = str(authority.get("aws_region") or "").strip()
    backend = str(authority.get("backend_url") or "").strip()
    if not capability or not region or not backend:
        raise PulumiExecError("Pulumi AWS/backend authority is incomplete")
    try:
        env = dict(
            aws_env_loader(project, region, capability_type=capability)
        )
    except Exception as exc:
        raise PulumiExecError(
            "Pulumi AWS authority could not be materialized from the "
            f"machine-local {capability} capability for project {project!r} "
            "(cause: machine_capability_unavailable). Restore access_key_id "
            "and secret_access_key with `yoke projects capability secret set` "
            "or, in GitHub Actions, run aws-actions/configure-aws-credentials "
            "before retrying."
        ) from exc
    for name in _AMBIENT_GITHUB_ENV:
        env.pop(name, None)
    token = ""
    if str(authority.get("github_repo") or "").strip():
        try:
            github_project = str(
                authority.get("github_project") or project
            ).strip()
            github = github_auth_loader(
                github_project,
                required_permissions=dict(authority.get("github_permissions") or {}),
            )
            token = str(github.token or "").strip()
        except Exception as exc:
            raise PulumiExecError(
                "Pulumi GitHub App authority could not be materialized for "
                f"project {github_project!r} (cause: app_authority_unavailable). "
                "Run `yoke github status` and `yoke projects github-binding "
                f"status --project {github_project} --json`; reconnect or "
                "repair the binding before retrying."
            ) from exc
        resolved_repo = str(getattr(github, "repo", "") or "").strip().casefold()
        expected_repo = str(authority.get("github_repo") or "").strip().casefold()
        if resolved_repo != expected_repo:
            raise PulumiExecError(
                "Pulumi GitHub token repository does not match stack authority"
            )
        env["GITHUB_TOKEN"] = token
        env["RUNNER_FLEET_GITHUB_TOKEN"] = token
    env["PULUMI_BACKEND_URL"] = backend
    operator = payload.get("operator_state") or {}
    secret_terms = [
        token,
        str(operator.get("secrets_provider") or ""),
        str(operator.get("encrypted_key") or ""),
    ]
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        secret_terms.append(str(env.get(name) or ""))
    return env, tuple(value for value in secret_terms if value)


def _write_owner_only(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def _new_owner_only_output(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


__all__ = ["PulumiExecError", "execute_pulumi_command"]
