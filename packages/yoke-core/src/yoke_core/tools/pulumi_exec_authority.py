"""Authority materialization for bounded Pulumi execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from yoke_core.tools.pulumi_exec_types import (
    AMBIENT_GITHUB_ENV,
    PulumiExecError,
)


def authority_env(
    project: str,
    authority: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    aws_env_loader: Callable[..., Mapping[str, str]],
    github_auth_loader: Callable[..., Any],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Materialize the child env and redaction terms for one stack."""
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
    resolved_repo = ""
    if str(authority.get("github_repo") or "").strip():
        github_project = str(authority.get("github_project") or project).strip()
        try:
            github = github_auth_loader(
                github_project,
                required_permissions=dict(
                    authority.get("github_permissions") or {}
                ),
            )
            token = str(github.token or "").strip()
        except Exception as exc:
            safe_message = getattr(exc, "pulumi_safe_message", "")
            safe_detail = (
                f" Detail: {safe_message}"
                if isinstance(safe_message, str) and safe_message.strip()
                else ""
            )
            raise PulumiExecError(
                "Pulumi GitHub App authority could not be materialized for "
                f"project {github_project!r} "
                f"(cause: app_authority_unavailable).{safe_detail} "
                "Run `yoke github "
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
    secret_terms = [token, *(str(term) for term in payload.get("stack_secrets") or ())]
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        secret_terms.append(str(env.get(name) or ""))
    return env, tuple(value for value in secret_terms if value)


__all__ = ["authority_env"]
