# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_github_webhook.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi reconciliation for the runner fleet's GitHub repository webhook."""

from __future__ import annotations

import hmac
import os

import pulumi
import pulumi_github as github


def require_webhook_token_environment() -> None:
    """Verify the intent marker matches pulumi-github's ambient token."""
    token = os.environ.get("RUNNER_FLEET_WEBHOOK_TOKEN", "")
    provider_token = os.environ.get("GITHUB_TOKEN", "")
    if not token.strip():
        raise pulumi.RunError(
            "runner-fleet stack requires RUNNER_FLEET_WEBHOOK_TOKEN "
            "with repository_hooks: write permission"
        )
    if not provider_token or not hmac.compare_digest(token, provider_token):
        raise pulumi.RunError(
            "runner-fleet stack requires GITHUB_TOKEN to match "
            "RUNNER_FLEET_WEBHOOK_TOKEN for process-only provider auth"
        )


def create_repository_webhook(
    *,
    owner: str,
    repository: str,
    api_url: str,
    webhook_url: pulumi.Input[str],
    webhook_secret: pulumi.Input[str],
    child_opts: pulumi.ResourceOptions,
) -> github.RepositoryWebhook:
    """Reconcile the existing repository webhook under stable Pulumi names."""
    require_webhook_token_environment()
    provider_token = os.environ.pop("GITHUB_TOKEN")
    try:
        provider = github.Provider(
            "runnerFleetGithubProvider",
            owner=owner,
            # pulumi-github's canonical provider input ends in `/`; preserve
            # that form so explicit origin pinning does not create URL churn.
            base_url=api_url.rstrip("/") + "/",
            opts=child_opts,
        )
    finally:
        os.environ["GITHUB_TOKEN"] = provider_token
    return github.RepositoryWebhook(
        "runnerFleetGithubWebhook",
        repository=repository,
        events=["workflow_job"],
        active=True,
        configuration={
            "url": webhook_url,
            "content_type": "json",
            "insecure_ssl": False,
            "secret": webhook_secret,
        },
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(provider=provider),
        ),
    )


__all__ = [
    "create_repository_webhook",
    "require_webhook_token_environment",
]
