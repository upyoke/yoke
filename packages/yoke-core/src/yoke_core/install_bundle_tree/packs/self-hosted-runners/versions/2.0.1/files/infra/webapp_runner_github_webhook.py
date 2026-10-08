"""Pulumi reconciliation for runner-fleet GitHub repository automation."""

from __future__ import annotations

import json
from typing import Sequence

import pulumi
import pulumi_github as github

from webapp_github_repository_provider import (
    create_repository_provider,
    require_repository_token_environment as require_repository_token,
)


def require_repository_token_environment() -> None:
    """Verify the intent marker matches pulumi-github's ambient token."""
    require_repository_token(
        (
            "repository_hooks: write",
            "actions_variables: write",
        ),
        authority_name="runner-fleet stack",
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
    provider = create_repository_provider(
        "runnerFleetGithubProvider",
        owner=owner,
        api_url=api_url,
        required_permissions=(
            "repository_hooks: write",
            "actions_variables: write",
        ),
        authority_name="runner-fleet stack",
        opts=child_opts,
    )
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
