# AUTO-GENERATED template source: templates/webapp/infra/webapp_registry_github_variables.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""GitHub Actions role routing owned by the registry stack."""

from __future__ import annotations

import pulumi
import pulumi_github as github

from webapp_github_repository_provider import create_repository_provider


INFRASTRUCTURE_ROLE_VARIABLE = "YOKE_INFRA_CI_ROLE_ARN"
DELIVERY_ROLE_VARIABLE = "YOKE_DELIVERY_CI_ROLE_ARN"


def create_ci_role_variables(
    *,
    github_repo: str,
    github_api_url: str,
    infrastructure_role_arn: pulumi.Input[str],
    delivery_role_arn: pulumi.Input[str],
    child_opts: pulumi.ResourceOptions,
) -> tuple[github.ActionsVariable, github.ActionsVariable]:
    """Converge non-secret workflow routing to the stack-owned roles."""
    owner, separator, repository = github_repo.partition("/")
    if not separator or not owner.strip() or not repository.strip() or "/" in repository:
        raise pulumi.RunError("github_repo must use the exact owner/repository form")
    provider = create_repository_provider(
        "githubCiRoleVariableProvider",
        owner=owner,
        api_url=github_api_url,
        required_permissions=(
            "actions_variables: read for preview or write for apply",
        ),
        authority_name="registry stack",
        opts=child_opts,
    )
    provider_opts = pulumi.ResourceOptions.merge(
        child_opts,
        pulumi.ResourceOptions(provider=provider),
    )
    infrastructure = github.ActionsVariable(
        "githubActionsInfrastructureRoleVariable",
        repository=repository,
        variable_name=INFRASTRUCTURE_ROLE_VARIABLE,
        value=infrastructure_role_arn,
        opts=provider_opts,
    )
    delivery = github.ActionsVariable(
        "githubActionsDeliveryRoleVariable",
        repository=repository,
        variable_name=DELIVERY_ROLE_VARIABLE,
        value=delivery_role_arn,
        opts=provider_opts,
    )
    return infrastructure, delivery


__all__ = [
    "DELIVERY_ROLE_VARIABLE",
    "INFRASTRUCTURE_ROLE_VARIABLE",
    "create_ci_role_variables",
]
