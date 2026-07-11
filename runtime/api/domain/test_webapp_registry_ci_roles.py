"""Pulumi registry-stack OIDC role separation."""

from __future__ import annotations

import json

from runtime.api.domain.test_webapp_registry_stack import _registry_stack


def test_github_oidc_roles_split_infrastructure_from_delivery(monkeypatch):
    app_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:yoke/prod/github-app-private-key-AbCdEf"
    )
    recorder, stack = _registry_stack(
        monkeypatch,
        github_repo="upyoke/platform",
        distribution_bucket_names=["upyoke-distribution-prod"],
        github_app_private_key_secret_arns=[app_secret],
    )

    infrastructure = recorder.single("githubActionsCiRole")
    delivery = recorder.single("githubActionsDeliveryRole")
    assert infrastructure.kwargs["name"] == "yoke-ci-github"
    assert delivery.kwargs["name"] == "yoke-delivery-ci-github"
    infra_subjects = json.loads(infrastructure.kwargs["assume_role_policy"])[
        "Statement"
    ][0]["Condition"]["StringEquals"][
        "token.actions.githubusercontent.com:sub"
    ]
    delivery_subjects = json.loads(delivery.kwargs["assume_role_policy"])[
        "Statement"
    ][0]["Condition"]["StringEquals"][
        "token.actions.githubusercontent.com:sub"
    ]
    assert infra_subjects == ["repo:upyoke/platform:ref:refs/heads/main"]
    assert delivery_subjects == [
        "repo:upyoke/platform:ref:refs/heads/main",
        "repo:upyoke/platform:ref:refs/heads/stage",
    ]
    attachment = recorder.single("githubActionsInfrastructureViewOnly")
    assert attachment.kwargs["role"] == "yoke-ci-github"
    assert attachment.kwargs["policy_arn"].endswith(
        ":policy/job-function/ViewOnlyAccess"
    )
    infrastructure_deny = json.loads(
        recorder.single("githubActionsInfrastructureBoundary").kwargs[
            "policy"
        ]
    )["Statement"][-1]
    assert infrastructure_deny["Effect"] == "Deny"
    assert app_secret in infrastructure_deny["Resource"]
    policy = json.loads(
        recorder.single("githubActionsDeliveryPolicy").kwargs["policy"]
    )
    deny = next(
        statement for statement in policy["Statement"]
        if statement.get("Sid") == "DenyGitHubAppPrivateKeys"
    )
    assert app_secret in deny["Resource"]
    assert recorder.exports["githubActionsInfrastructureRoleArn"].value == (
        stack.infrastructure_role.arn.value
    )
    assert recorder.exports["githubActionsDeliveryRoleArn"].value == (
        stack.delivery_role.arn.value
    )
    provider = recorder.single("githubCiRoleVariableProvider")
    assert provider.kwargs == {
        "owner": "upyoke",
        "base_url": "https://api.github.com/",
    }
    infrastructure_variable = recorder.single(
        "githubActionsInfrastructureRoleVariable"
    )
    delivery_variable = recorder.single("githubActionsDeliveryRoleVariable")
    assert infrastructure_variable.kwargs["repository"] == "platform"
    assert infrastructure_variable.kwargs["variable_name"] == (
        "YOKE_INFRA_CI_ROLE_ARN"
    )
    assert infrastructure_variable.kwargs["value"].value == (
        stack.infrastructure_role.arn.value
    )
    assert delivery_variable.kwargs["repository"] == "platform"
    assert delivery_variable.kwargs["variable_name"] == (
        "YOKE_DELIVERY_CI_ROLE_ARN"
    )
    assert delivery_variable.kwargs["value"].value == (
        stack.delivery_role.arn.value
    )
    assert infrastructure_variable.opts.provider is provider
    assert delivery_variable.opts.provider is provider
