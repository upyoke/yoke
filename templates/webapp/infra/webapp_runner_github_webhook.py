# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_github_webhook.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi reconciliation for runner-fleet GitHub repository automation."""

from __future__ import annotations

import hmac
import json
import os
from typing import Sequence

import pulumi
import pulumi_github as github


def require_repository_token_environment() -> None:
    """Verify the intent marker matches pulumi-github's ambient token."""
    token = os.environ.get("RUNNER_FLEET_GITHUB_TOKEN", "")
    provider_token = os.environ.get("GITHUB_TOKEN", "")
    if not token.strip():
        raise pulumi.RunError(
            "runner-fleet stack requires RUNNER_FLEET_GITHUB_TOKEN "
            "with required permissions: repository_hooks: write, "
            "actions_variables: write"
        )
    if not provider_token or not hmac.compare_digest(token, provider_token):
        raise pulumi.RunError(
            "runner-fleet stack requires GITHUB_TOKEN to match "
            "RUNNER_FLEET_GITHUB_TOKEN for process-only provider auth"
        )


def create_repository_automation(
    *,
    owner: str,
    repository: str,
    api_url: str,
    webhook_url: pulumi.Input[str],
    webhook_secret: pulumi.Input[str],
    variable_name: str,
    runner_labels: Sequence[str],
    routing_enabled: bool,
    ingress_ready: Sequence[pulumi.Resource],
    child_opts: pulumi.ResourceOptions,
) -> tuple[github.RepositoryWebhook, github.ActionsVariable | None]:
    """Reconcile the repository webhook and workflow runner route."""
    require_repository_token_environment()
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
    webhook = github.RepositoryWebhook(
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
            pulumi.ResourceOptions(
                provider=provider,
                depends_on=list(ingress_ready),
            ),
        ),
    )
    actions_variable = None
    if routing_enabled:
        actions_variable = github.ActionsVariable(
            "runnerFleetRoutingVariable",
            repository=repository,
            variable_name=variable_name,
            value=json.dumps(list(runner_labels), separators=(",", ":")),
            opts=pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(
                    provider=provider,
                    depends_on=[webhook, *ingress_ready],
                ),
            ),
        )
    return webhook, actions_variable


__all__ = [
    "create_repository_automation",
    "require_repository_token_environment",
]
