"""Authority materialization for bounded Pulumi execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from yoke_core.tools.pulumi_exec_types import (
    AMBIENT_GITHUB_ENV,
    PulumiExecError,
)
from yoke_core.tools.runner_fleet_authority_intent import (
    authority_intent_envelope_from_values,
)
from yoke_core.tools.runner_fleet_exec import (
    RUNNER_FLEET_AUTHORITY_INTENT_ENV,
    resolve_local_runner_fleet_github_auth,
)


def authority_env(
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
        env = dict(aws_env_loader(project, region, capability_type=capability))
    except Exception as exc:
        raise PulumiExecError(
            "Pulumi AWS authority could not be materialized from the "
            f"machine-local {capability} capability for project {project!r} "
            "(cause: machine_capability_unavailable). Restore access_key_id "
            "and secret_access_key with `yoke projects capability secret set` "
            "or, in GitHub Actions, run aws-actions/configure-aws-credentials "
            "before retrying."
        ) from exc
    for name in AMBIENT_GITHUB_ENV:
        env.pop(name, None)
    token = ""
    local_redaction_terms: tuple[str, ...] = ()
    if str(authority.get("github_repo") or "").strip():
        github_project = str(authority.get("github_project") or project).strip()
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
            values = {str(key): str(value) for key, value in raw_values.items()}
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


__all__ = ["authority_env"]
