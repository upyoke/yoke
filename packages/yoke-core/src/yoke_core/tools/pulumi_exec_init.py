"""Stack initialization for bounded Pulumi execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import sys
import tempfile
from typing import Any, TextIO

from yoke_core.domain import yaml_helper
from yoke_core.domain.deploy_remote import DEFAULT_AWS_CAPABILITY_TYPE
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE as PULUMI_STATE_CAPABILITY_TYPE,
)
from yoke_core.tools.pulumi_exec_file_backed import stage_file_backed_infra
from yoke_core.tools.pulumi_exec_files import new_owner_only_output
from yoke_core.tools.pulumi_exec_types import (
    AMBIENT_GITHUB_ENV,
    PulumiExecError,
)
from yoke_core.tools.redacted_process import run_redacted_child


def execute_pulumi_stack_init(
    project: str,
    stack: str,
    command: Sequence[str],
    *,
    project_root: Path,
    stack_file: Path,
    settings_loader: Callable[[str], ProjectRendererSettings],
    aws_env_loader: Callable[..., Mapping[str, str]],
    child_factory: Callable[..., Any] | None,
    out: TextIO | None,
    err: TextIO | None,
) -> int:
    """Initialize one stack, pinned to the capability's KMS key.

    Any stack name is accepted. ``stack_file`` is the stack's checked-in
    ``infra/Pulumi.<stack>.yaml``; the generated ``secretsprovider`` and ``encryptedkey`` lines are printed for
    the operator to commit into that file, and Yoke stores nothing.
    """
    requested_provider = _validated_init_provider(command)
    settings = settings_loader(project)
    if settings.project != project:
        raise PulumiExecError(
            "Pulumi project settings do not match the requested project"
        )
    state_settings = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE)
    if not isinstance(state_settings, Mapping):
        raise PulumiExecError(f"project {project!r} has no pulumi-state capability")
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

    _refuse_foreign_provider(stack_file, expected_provider)

    with tempfile.TemporaryDirectory(prefix="yoke-pulumi-exec-") as raw_temp:
        temp_root = Path(raw_temp)
        temp_root.chmod(0o700)
        render_root = temp_root / "render"
        infra_root = stage_file_backed_infra(project_root, stack, render_root, None)
        stack_path = infra_root / f"Pulumi.{stack}.yaml"
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
        return _report_file_stack_lines(
            stack_file, discovered_provider, encrypted_key, out or sys.stdout
        )


def _refuse_foreign_provider(stack_file: Path, expected_provider: str) -> None:
    declared = yaml_helper.read_top_level_scalars(stack_file, ("secretsprovider",))
    provider = str(declared.get("secretsprovider") or "").strip()
    if provider and provider != expected_provider:
        raise PulumiExecError(
            f"pulumi_secrets_provider_mismatch: {stack_file} declares "
            f"secretsprovider {provider!r} but the project's pulumi-state "
            f"capability pins {expected_provider!r}; correct the stack file "
            "and retry"
        )


def _report_file_stack_lines(
    stack_file: Path, provider: str, encrypted_key: str, sink: TextIO
) -> int:
    if not provider or not encrypted_key:
        raise PulumiExecError(
            "Pulumi stack was initialized but Pulumi wrote no secretsprovider "
            "and encryptedkey; run `pulumi stack export` for the stack and "
            f"add both lines to {stack_file} before retrying"
        )
    declared = yaml_helper.read_top_level_scalars(
        stack_file, ("secretsprovider", "encryptedkey")
    )
    lines = f"secretsprovider: {provider}\nencryptedkey: {encrypted_key}\n"
    if (
        str(declared.get("secretsprovider") or "").strip() == provider
        and str(declared.get("encryptedkey") or "").strip() == encrypted_key
    ):
        sink.write(f"Pulumi stack initialized; {stack_file} already carries:\n{lines}")
    else:
        sink.write(
            f"Pulumi stack initialized. Add these top-level lines to {stack_file} "
            f"and commit them; Yoke stores neither:\n{lines}"
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
