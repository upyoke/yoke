"""Declared-stack initialization for bounded Pulumi execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import sys
import tempfile
from typing import Any, TextIO

from yoke_core.domain import yaml_helper
from yoke_core.domain.deploy_remote import DEFAULT_AWS_CAPABILITY_TYPE
from yoke_core.domain.project_renderer import render_project
from yoke_core.domain.project_renderer_pulumi_stack_types import (
    gather_pulumi_stacks,
    pulumi_stack_name,
)
from yoke_core.domain.project_renderer_pulumi_values import gather_pulumi_values
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE as PULUMI_STATE_CAPABILITY_TYPE,
    validate_stack_state,
)
from yoke_core.tools.pulumi_exec_files import new_owner_only_output
from yoke_core.tools.pulumi_exec_types import (
    AMBIENT_GITHUB_ENV,
    PulumiExecError,
)
from yoke_core.tools.runner_fleet_redacted_process import run_redacted_child


def execute_pulumi_stack_init(
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
        stdout_capture = new_owner_only_output(stdout_path)
        stderr_capture = new_owner_only_output(stderr_path)
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
                    "pulumi", "stack", "init", stack,
                    "--secrets-provider", requested_provider,
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
            stdout_path, out or sys.stdout, secret_terms=(encrypted_key,)
        )
        _forward_init_output(
            stderr_path, err or sys.stderr, secret_terms=(encrypted_key,)
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
            receipt = dict(state_importer(
                project=project,
                stack_name=stack,
                secrets_provider=discovered_provider,
                encrypted_key=encrypted_key,
                apply=True,
            ))
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
        env = dict(aws_env_loader(
            project, region, capability_type=DEFAULT_AWS_CAPABILITY_TYPE,
        ))
    except Exception as exc:
        raise PulumiExecError(
            "Pulumi AWS authority could not be materialized from the "
            f"machine-local aws-admin capability for project {project!r} "
            "(cause: machine_capability_unavailable)."
        ) from exc
    for name in AMBIENT_GITHUB_ENV:
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


__all__ = ["execute_pulumi_stack_init"]
