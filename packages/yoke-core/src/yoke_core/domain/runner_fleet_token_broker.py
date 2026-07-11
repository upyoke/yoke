"""Hosted issuance of repository-scoped runner-fleet automation tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
import hmac
from typing import Any, Callable

from yoke_contracts.github_app_installation_permissions import (
    ACCESS_READ,
    ACTIONS_VARIABLES_PERMISSION,
    REPOSITORY_HOOKS_PERMISSION,
)

from yoke_core.domain import json_helper
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain.project_renderer_settings_snapshot import (
    build_pulumi_stack_config,
    settings_from_stack_config,
)
from yoke_core.tools.runner_fleet_authority_intent import (
    authority_intent_from_settings,
)


class RunnerFleetTokenBrokerError(RuntimeError):
    """Token issuance was refused before exposing any credential material."""

    code = "runner_fleet_token_unavailable"


class RunnerFleetAuthorityMismatch(RunnerFleetTokenBrokerError):
    """The caller's renderer snapshot no longer matches DB authority."""

    code = "runner_fleet_authority_mismatch"


@dataclass(frozen=True)
class RunnerFleetTokenGrant:
    token: str = field(repr=False)
    expires_at: str
    repository: str


_REPOSITORY_AUTOMATION_PERMISSIONS = {
    ACTIONS_VARIABLES_PERMISSION: ACCESS_READ,
    REPOSITORY_HOOKS_PERMISSION: ACCESS_READ,
}


def issue_runner_fleet_token(
    conn: Any,
    *,
    project: str,
    authority_sha256: str,
    auth_resolver: Callable[..., Any] = resolve_project_github_auth,
) -> RunnerFleetTokenGrant:
    """Mint one token after matching the caller to current DB authority."""
    payload = build_pulumi_stack_config(conn, project)
    settings = settings_from_stack_config(payload)
    try:
        envelope, values, _aws_capability, _region = (
            authority_intent_from_settings(settings)
        )
        intent = json_helper.loads_text(envelope)
        expected_digest = str(intent.get("sha256") or "")
    except (KeyError, TypeError, ValueError) as exc:
        raise RunnerFleetTokenBrokerError(
            "current runner-fleet authority is incomplete"
        ) from exc
    if not hmac.compare_digest(expected_digest, authority_sha256):
        raise RunnerFleetAuthorityMismatch(
            "runner-fleet settings changed after the CI snapshot was rendered"
        )

    try:
        auth = auth_resolver(
            settings.project,
            conn=conn,
            required_permissions=_REPOSITORY_AUTOMATION_PERMISSIONS,
        )
    except Exception as exc:
        raise RunnerFleetTokenBrokerError(
            "repository automation authority is unavailable"
        ) from exc
    expected_repo = values["runner_fleet_repo"]
    expected_installation = values["runner_fleet_github_installation_id"]
    if (
        auth.token_source != "github_app_installation"
        or auth.repo != expected_repo
        or auth.installation_id != expected_installation
    ):
        raise RunnerFleetTokenBrokerError(
            "repository automation authority does not match runner-fleet settings"
        )
    token = str(auth.token or "").strip()
    expires_at = str(auth.token_expires_at or "").strip()
    if not token or not expires_at:
        raise RunnerFleetTokenBrokerError(
            "repository automation token is missing expiry metadata"
        )
    return RunnerFleetTokenGrant(
        token=token,
        expires_at=expires_at,
        repository=expected_repo,
    )


__all__ = [
    "RunnerFleetAuthorityMismatch",
    "RunnerFleetTokenBrokerError",
    "RunnerFleetTokenGrant",
    "issue_runner_fleet_token",
]
