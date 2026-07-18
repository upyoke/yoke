"""Execute a narrow Pulumi operator command from stack-scoped authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, TextIO

from yoke_core.domain import yaml_helper
from yoke_core.domain.deploy_remote import (
    DEFAULT_AWS_CAPABILITY_TYPE,
    aws_machine_capability_env,
)
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain.project_renderer import render_project
from yoke_core.domain.project_renderer_pulumi_stack_types import (
    gather_pulumi_stacks,
    pulumi_stack_name,
)
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.domain.project_renderer_pulumi_values import gather_pulumi_values
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    load_project_renderer_settings,
)
from yoke_core.domain.projects_pulumi_state_checkpoint_import import (
    import_checkpoint_state,
)
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE as PULUMI_STATE_CAPABILITY_TYPE,
    validate_stack_state,
)
from yoke_core.tools.runner_fleet_redacted_process import run_redacted_child
from yoke_core.tools.runner_fleet_exec import (
    RUNNER_FLEET_AUTHORITY_INTENT_ENV,
    resolve_local_runner_fleet_github_auth,
)
from yoke_core.tools.runner_fleet_authority_intent import (
    authority_intent_envelope_from_values,
)


_ALLOWED_COMMANDS = frozenset({"init", "preview", "refresh", "import", "up"})
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
_UP_FLAGS = frozenset({
    "--diff", "--non-interactive", "--refresh", "--suppress-outputs", "--yes",
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
        return _execute_pulumi_stack_init(
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


def _validated_command(
    stack: str, command: Sequence[str]
) -> tuple[list[str], Path | None]:
    parts = [str(part) for part in command]
    if not parts or parts[0] not in _ALLOWED_COMMANDS:
        raise PulumiExecError(
            "Pulumi exec allows only init, preview, refresh, import, and up"
        )
    operation = parts[0]
    if operation == "init":
        raise PulumiExecError("Pulumi init must use the stack bootstrap boundary")
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
    elif operation == "up":
        _validate_up_args(args)
    else:
        _validate_flag_args(args, _REFRESH_FLAGS)
    args = _without_stack_flag(args)
    return ["pulumi", operation, *args, "--stack", stack], json_output


def _execute_pulumi_stack_init(
    project: str,
    stack: str,
    command: Sequence[str],
    *,
    project_root: Path,
    settings_loader: Callable[[str], ProjectRendererSettings],
    state_importer: Callable[..., Mapping[str, Any]],
    aws_env_loader: Callable[..., Mapping[str, str]],
    child_factory: Callable[..., Any] | None,
    out: TextIO | None,
    err: TextIO | None,
) -> int:
    """Initialize one declared stack and persist its generated operator state."""
    requested_provider = _validated_init_provider(command)
    settings = settings_loader(project)
    if settings.project != project:
        raise PulumiExecError(
            "Pulumi renderer settings do not match the requested project"
        )
    state_settings = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE)
    if not isinstance(state_settings, Mapping):
        raise PulumiExecError(f"project {project!r} has no pulumi-state capability")
    raw_stack_types = state_settings.get("stacks")
    if not isinstance(raw_stack_types, list) or not raw_stack_types:
        raise PulumiExecError(
            "Pulumi stack init requires an explicit non-empty pulumi-state "
            "stacks declaration"
        )
    try:
        declared_types = gather_pulumi_stacks(project, project_root, settings)
        values = gather_pulumi_values(
            project, project_root, settings, pulumi_stack=stack
        )
        declared_names = {
            pulumi_stack_name(stack_type, settings, values)
            for stack_type in declared_types
        }
    except ValueError as exc:
        raise PulumiExecError(str(exc)) from exc
    if stack not in declared_names:
        raise PulumiExecError(
            f"Pulumi stack {stack!r} is not an exact declared project stack"
        )
    try:
        operator_state = validate_stack_state(state_settings.get("stack_state", {}))
    except ValueError as exc:
        raise PulumiExecError("stored Pulumi operator state is invalid") from exc
    if stack in operator_state:
        raise PulumiExecError(
            f"Pulumi operator state is already registered for stack {stack!r}"
        )

    aws_settings = settings.capabilities.get(DEFAULT_AWS_CAPABILITY_TYPE)
    if not isinstance(aws_settings, Mapping):
        raise PulumiExecError(f"project {project!r} has no aws-admin capability")
    region = str(aws_settings.get("region") or "").strip()
    state_bucket = str(state_settings.get("state_bucket") or "").strip()
    kms_key_alias = str(state_settings.get("kms_key_alias") or "").strip()
    if not region or not state_bucket or not kms_key_alias:
        raise PulumiExecError(
            "Pulumi stack init requires aws-admin region plus explicit "
            "pulumi-state state_bucket and kms_key_alias settings"
        )
    expected_provider = f"awskms://{kms_key_alias}?region={region}"
    if requested_provider != expected_provider:
        raise PulumiExecError(
            "Pulumi init secrets provider does not match capability authority; "
            f"expected {expected_provider!r}"
        )

    with tempfile.TemporaryDirectory(prefix="yoke-pulumi-exec-") as raw_temp:
        temp_root = Path(raw_temp)
        temp_root.chmod(0o700)
        render_root = temp_root / "render"
        try:
            render_project(
                project,
                write=True,
                only="pulumi",
                project_root=project_root,
                output_dir=render_root,
                settings=settings,
                pulumi_stack=stack,
            )
        except ValueError as exc:
            raise PulumiExecError(str(exc)) from exc
        infra_root = render_root / "infra"
        stack_path = infra_root / f"Pulumi.{stack}.yaml"
        if not stack_path.is_file():
            raise PulumiExecError(
                "declared Pulumi stack did not render an exact stack config"
            )
        child_env, redaction_terms = _bootstrap_authority_env(
            project,
            region=region,
            backend_url=f"s3://{state_bucket}?region={region}",
            provider=requested_provider,
            aws_env_loader=aws_env_loader,
        )
        stdout_path = temp_root / "init.stdout"
        stderr_path = temp_root / "init.stderr"
        stdout_capture = _new_owner_only_output(stdout_path)
        stderr_capture = _new_owner_only_output(stderr_path)
        try:
            kwargs: dict[str, Any] = {
                "env": child_env,
                "redaction_terms": redaction_terms,
                "out": stdout_capture,
                "err": stderr_capture,
                "cwd": infra_root,
            }
            if child_factory is not None:
                kwargs["child_factory"] = child_factory
            result = run_redacted_child(
                [
                    "pulumi",
                    "stack",
                    "init",
                    stack,
                    "--secrets-provider",
                    requested_provider,
                    "--non-interactive",
                ],
                **kwargs,
            )
        finally:
            stdout_capture.close()
            stderr_capture.close()

        metadata = yaml_helper.read_top_level_scalars(
            stack_path, ("secretsprovider", "encryptedkey")
        )
        encrypted_key = str(metadata.get("encryptedkey") or "").strip()
        _forward_init_output(
            stdout_path,
            out or sys.stdout,
            secret_terms=(encrypted_key,),
        )
        _forward_init_output(
            stderr_path,
            err or sys.stderr,
            secret_terms=(encrypted_key,),
        )
        if result.returncode:
            return result.returncode
        discovered_provider = str(metadata.get("secretsprovider") or "").strip()
        if discovered_provider != requested_provider or not encrypted_key:
            raise PulumiExecError(
                "Pulumi stack was initialized but generated operator-state "
                "metadata is incomplete; export its checkpoint and recover with "
                "`yoke projects pulumi-state checkpoint-import`"
            )
        try:
            receipt = dict(
                state_importer(
                    project=project,
                    stack_name=stack,
                    secrets_provider=discovered_provider,
                    encrypted_key=encrypted_key,
                    apply=True,
                )
            )
        except Exception as exc:
            raise PulumiExecError(
                "Pulumi stack was initialized but typed operator-state "
                "persistence failed; export its checkpoint and recover with "
                "`yoke projects pulumi-state checkpoint-import`"
            ) from exc
        receipt_digest = str(receipt.get("receipt_digest") or "").strip()
        if not receipt_digest:
            raise PulumiExecError(
                "Pulumi stack was initialized but operator-state persistence "
                "returned no receipt digest"
            )
        sink = out or sys.stdout
        sink.write(
            "Pulumi stack initialized and operator state registered: "
            f"{project}|{stack}|{receipt_digest}\n"
        )
        sink.flush()
        return 0


def _validated_init_provider(command: Sequence[str]) -> str:
    parts = [str(part) for part in command]
    if len(parts) != 3 or parts[:2] != ["init", "--secrets-provider"]:
        raise PulumiExecError(
            "Pulumi init requires exactly --secrets-provider <awskms URI>"
        )
    provider = parts[2].strip()
    if not provider.startswith("awskms://"):
        raise PulumiExecError("Pulumi init secrets provider must use awskms://")
    return provider


def _bootstrap_authority_env(
    project: str,
    *,
    region: str,
    backend_url: str,
    provider: str,
    aws_env_loader: Callable[..., Mapping[str, str]],
) -> tuple[dict[str, str], tuple[str, ...]]:
    try:
        env = dict(
            aws_env_loader(
                project,
                region,
                capability_type=DEFAULT_AWS_CAPABILITY_TYPE,
            )
        )
    except Exception as exc:
        raise PulumiExecError(
            "Pulumi AWS authority could not be materialized from the "
            f"machine-local aws-admin capability for project {project!r} "
            "(cause: machine_capability_unavailable)."
        ) from exc
    for name in _AMBIENT_GITHUB_ENV:
        env.pop(name, None)
    env["PULUMI_BACKEND_URL"] = backend_url
    secret_terms = [provider]
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        secret_terms.append(str(env.get(name) or ""))
    return env, tuple(value for value in secret_terms if value)


def _forward_init_output(
    path: Path, destination: TextIO, *, secret_terms: Sequence[str]
) -> None:
    text = path.read_text(encoding="utf-8")
    for term in secret_terms:
        if term:
            text = text.replace(term, "[REDACTED]")
    if text:
        destination.write(text)
        destination.flush()


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


def _validate_up_args(args: Sequence[str]) -> None:
    _validate_flag_args(args, _UP_FLAGS)
    selected = set(_without_stack_flag(args))
    missing = [
        required
        for required in ("--yes", "--non-interactive")
        if required not in selected
    ]
    if missing:
        raise PulumiExecError(
            "pulumi up requires --yes and --non-interactive"
        )


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
    bootstrap_local_authority: bool = False,
    local_github_auth_loader: Callable[..., Any] = (
        resolve_local_runner_fleet_github_auth
    ),
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
    local_redaction_terms: tuple[str, ...] = ()
    if str(authority.get("github_repo") or "").strip():
        github_project = str(
            authority.get("github_project") or project
        ).strip()
        if bootstrap_local_authority:
            if payload.get("stack_kind") != "runner-fleet":
                raise PulumiExecError(
                    "local GitHub bootstrap authority is limited to the "
                    "runner-fleet stack"
                )
            raw_values = payload.get("render_values")
            if not isinstance(raw_values, Mapping):
                raise PulumiExecError(
                    "runner-fleet render values are missing from stack config"
                )
            values = {
                str(key): str(value) for key, value in raw_values.items()
            }
            try:
                github = local_github_auth_loader(
                    values, region=region, aws_env=env,
                )
                token = str(github.token or "").strip()
                local_redaction_terms = tuple(github.redaction_terms)
                env[RUNNER_FLEET_AUTHORITY_INTENT_ENV] = (
                    authority_intent_envelope_from_values(
                        project=str(payload.get("project_slug") or ""),
                        deploy_namespace=values["deploy_namespace"],
                        stack_name=str(payload.get("stack_name") or ""),
                        values=values,
                        aws_capability=capability,
                        aws_region=region,
                    )
                )
            except Exception as exc:
                raise PulumiExecError(
                    "Pulumi local GitHub App bootstrap authority could not be "
                    f"materialized for project {github_project!r} "
                    "(cause: app_authority_unavailable)."
                ) from exc
        else:
            try:
                github = github_auth_loader(
                    github_project,
                    required_permissions=dict(
                        authority.get("github_permissions") or {}
                    ),
                )
                token = str(github.token or "").strip()
            except Exception as exc:
                raise PulumiExecError(
                    "Pulumi GitHub App authority could not be materialized for "
                    f"project {github_project!r} "
                    "(cause: app_authority_unavailable). Run `yoke github "
                    "status` and `yoke projects github-binding status "
                    f"--project {github_project} --json`; reconnect or repair "
                    "the binding before retrying."
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
    secret_terms.extend(local_redaction_terms)
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
