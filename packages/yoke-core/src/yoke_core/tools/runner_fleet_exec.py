"""Run runner-fleet admin commands with ephemeral GitHub App authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, TextIO

from yoke_contracts.github_app_installation_permissions import (
    ACCESS_WRITE,
    ACTIONS_VARIABLES_PERMISSION,
    REPOSITORY_HOOKS_PERMISSION,
)

from yoke_core.domain import json_helper
from yoke_core.domain.deploy_remote import aws_capability_env
from yoke_core.domain.github_app_installation_tokens import (
    mint_installation_token,
)
from yoke_core.domain.github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    RunnerFleetSettings,
    validate as validate_runner_fleet_settings,
)
from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_values,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from yoke_core.domain.project_renderer_settings_snapshot import (
    settings_from_stack_config,
)
from yoke_core.domain.yoke_cloud_db_authority import load_secret_string
from yoke_core.tools.runner_fleet_authority_intent import (
    authority_intent_envelope,
)
from yoke_core.tools.runner_fleet_redacted_process import (
    RedactedProcessError,
    run_redacted_child,
)


RUNNER_FLEET_GITHUB_TOKEN_ENV = "RUNNER_FLEET_GITHUB_TOKEN"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
RUNNER_FLEET_AUTHORITY_INTENT_ENV = "YOKE_RUNNER_FLEET_AUTHORITY_INTENT"
RUNNER_FLEET_TOKEN_SOURCE_ENV = "YOKE_RUNNER_FLEET_TOKEN_SOURCE"
_UNINTENDED_GITHUB_AUTH_ENV = frozenset({
    "GH_ENTERPRISE_TOKEN",
    "GH_TOKEN",
    "GITHUB_APP_ID",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_APP_PEM_FILE",
    "GITHUB_BASE_URL",
    "GITHUB_ENTERPRISE_TOKEN",
    "GITHUB_ORGANIZATION",
    "GITHUB_OWNER",
})


class RunnerFleetExecError(RuntimeError):
    """A runner-fleet child command could not acquire safe authority."""


def execute_runner_fleet_command(
    project: str,
    settings_file: Path | str,
    command: Sequence[str],
    *,
    aws_env_loader: Callable[..., Mapping[str, str]] = (
        aws_capability_env
    ),
    secret_loader: Callable[..., str] = load_secret_string,
    token_minter: Callable[..., Any] = mint_installation_token,
    hosted_token_loader: Callable[
        [str, str, Mapping[str, str]], str
    ] | None = None,
    child_factory: Callable[..., Any] = subprocess.Popen,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run *command* with one repository-scoped installation token.

    The versioned renderer snapshot is the sole configuration input. The
    GitHub Actions must acquire its token from the hosted control plane, where
    App key material stays server-side. Local operator runs may use the direct
    AWS secret path. Tokens remain in memory and child output is redacted.
    """
    selected_project = str(project or "").strip()
    selected_command = tuple(str(part) for part in command)
    if not selected_project:
        raise RunnerFleetExecError("runner-fleet project is required")
    if not selected_command:
        raise RunnerFleetExecError("runner-fleet child command is required")

    settings = _settings_for_project(
        selected_project, Path(settings_file),
    )
    values = _enabled_runner_fleet_values(settings)
    aws_capability, region = _runner_aws_authority(settings)
    try:
        authority_intent = authority_intent_envelope(
            settings,
            values,
            aws_capability=aws_capability,
            aws_region=region,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunnerFleetExecError(
            "runner-fleet authority intent could not be constructed"
        ) from exc

    try:
        aws_env = dict(aws_env_loader(
            selected_project,
            region,
            capability_type=aws_capability,
        ))
    except Exception as exc:
        raise RunnerFleetExecError(
            f"AWS capability {aws_capability!r} credentials could not be "
            "materialized"
        ) from exc

    private_key_pem = ""
    if _hosted_token_required():
        if hosted_token_loader is None:
            raise RunnerFleetExecError(
                "hosted runner-fleet token authority is required; configure "
                "the AWS runner broker"
            )
        try:
            token = str(
                hosted_token_loader(
                    selected_project, authority_intent, aws_env,
                ) or ""
            ).strip()
        except Exception as exc:
            raise RunnerFleetExecError(
                "hosted runner-fleet token authority is unavailable"
            ) from exc
        if not token:
            raise RunnerFleetExecError(
                "hosted runner-fleet token authority returned an empty token"
            )
    else:
        private_key_pem = _load_private_key(
            values["runner_fleet_github_private_key_secret_arn"],
            region=region,
            aws_env=aws_env,
            secret_loader=secret_loader,
        )
        token = _mint_repository_automation_token(
            values,
            private_key_pem=private_key_pem,
            token_minter=token_minter,
        )

    child_env = dict(aws_env)
    # Remove alternative GitHub CLI/App credentials, then overwrite the two
    # intentional aliases. This prevents Pulumi or a provider fallback from
    # selecting broader ambient authority.
    for name in _UNINTENDED_GITHUB_AUTH_ENV:
        child_env.pop(name, None)
    child_env[RUNNER_FLEET_AUTHORITY_INTENT_ENV] = authority_intent
    child_env[RUNNER_FLEET_GITHUB_TOKEN_ENV] = token
    child_env[GITHUB_TOKEN_ENV] = token
    redaction_terms = _redaction_terms(private_key_pem, token)
    try:
        completed = run_redacted_child(
            selected_command,
            env=child_env,
            redaction_terms=redaction_terms,
            child_factory=child_factory,
            out=out or sys.stdout,
            err=err or sys.stderr,
        )
    except FileNotFoundError:
        raise
    except RedactedProcessError as exc:
        raise RunnerFleetExecError(str(exc)) from exc
    return completed.returncode


def _settings_for_project(
    project: str, settings_file: Path,
) -> ProjectRendererSettings:
    try:
        payload = json_helper.load_path(settings_file)
    except (OSError, ValueError) as exc:
        raise RunnerFleetExecError(
            f"runner-fleet settings snapshot could not be loaded: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise RunnerFleetExecError(
            "runner-fleet settings snapshot must be a JSON object"
        )
    try:
        settings = settings_from_stack_config(payload)
    except ValueError as exc:
        raise RunnerFleetExecError(str(exc)) from exc

    envelope_project = str(payload.get("project_slug") or "").strip()
    if envelope_project != settings.project:
        raise RunnerFleetExecError(
            "runner-fleet settings envelope project does not match its "
            "renderer snapshot"
        )
    if project != settings.project:
        raise RunnerFleetExecError(
            f"runner-fleet settings project {settings.project!r} does not "
            f"match requested project {project!r}"
        )
    return settings


def _enabled_runner_fleet_values(
    settings: ProjectRendererSettings,
) -> dict[str, str]:
    try:
        return runner_fleet_values(
            settings,
            fallback_repo="",
            enabled=True,
        )
    except ValueError as exc:
        raise RunnerFleetExecError(str(exc)) from exc


def _runner_aws_authority(
    settings: ProjectRendererSettings,
) -> tuple[str, str]:
    raw_runner = settings.capabilities.get(RUNNER_FLEET_CAPABILITY_TYPE)
    selected = (
        validate_runner_fleet_settings(raw_runner)
        if raw_runner
        else RunnerFleetSettings()
    )
    capability_type = selected.aws_capability
    raw = settings.capabilities.get(capability_type)
    region = str(raw.get("region") or "").strip() if raw else ""
    if not region:
        raise RunnerFleetExecError(
            "runner-fleet settings snapshot selected AWS capability "
            f"{capability_type!r} but it declares no region"
        )
    return capability_type, region


def _load_private_key(
    secret_arn: str,
    *,
    region: str,
    aws_env: Mapping[str, str],
    secret_loader: Callable[..., str],
) -> str:
    try:
        private_key_pem = str(
            secret_loader(secret_arn, region=region, env=aws_env) or ""
        ).strip()
    except Exception as exc:
        raise RunnerFleetExecError(
            "GitHub App private key could not be loaded from Secrets Manager"
        ) from exc
    if not private_key_pem:
        raise RunnerFleetExecError(
            "GitHub App private key loaded from Secrets Manager was empty"
        )
    return private_key_pem


def _mint_repository_automation_token(
    values: Mapping[str, str],
    *,
    private_key_pem: str,
    token_minter: Callable[..., Any],
) -> str:
    try:
        minted = token_minter(
            issuer=values["runner_fleet_github_app_issuer"],
            private_key_pem=private_key_pem,
            installation_id=int(
                values["runner_fleet_github_installation_id"]
            ),
            api_url=values["runner_fleet_github_api_url"],
            repository_ids=[
                int(values["runner_fleet_github_repository_id"])
            ],
            permissions=_repository_automation_permissions(values),
        )
        token = str(getattr(minted, "token", "") or "").strip()
    except Exception as exc:
        raise RunnerFleetExecError(
            "repository automation installation token could not be minted"
        ) from exc
    if not token:
        raise RunnerFleetExecError(
            "repository automation installation token could not be minted"
        )
    return token


def _repository_automation_permissions(
    values: Mapping[str, str],
) -> dict[str, str]:
    del values
    return {
        ACTIONS_VARIABLES_PERMISSION: ACCESS_WRITE,
        REPOSITORY_HOOKS_PERMISSION: ACCESS_WRITE,
    }


def _hosted_token_required() -> bool:
    selected = os.environ.get(RUNNER_FLEET_TOKEN_SOURCE_ENV, "").strip().lower()
    if selected and selected not in {"hosted", "local"}:
        raise RunnerFleetExecError(
            f"{RUNNER_FLEET_TOKEN_SOURCE_ENV} must be 'hosted' or 'local'"
        )
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        if selected == "local":
            raise RunnerFleetExecError(
                "GitHub Actions cannot select local App private-key authority"
            )
        return True
    return selected == "hosted"


def _redaction_terms(private_key_pem: str, token: str) -> tuple[str, ...]:
    terms = {token}
    terms.update(
        line.strip()
        for line in private_key_pem.splitlines()
        if line.strip()
    )
    return tuple(sorted(terms, key=len, reverse=True))


__all__ = [
    "GITHUB_TOKEN_ENV",
    "RUNNER_FLEET_AUTHORITY_INTENT_ENV",
    "RUNNER_FLEET_GITHUB_TOKEN_ENV",
    "RUNNER_FLEET_TOKEN_SOURCE_ENV",
    "RunnerFleetExecError",
    "execute_runner_fleet_command",
]
