"""Pulumi registry-stack delivery role and retired preview authority."""

from __future__ import annotations

import json

from runtime.api.domain.test_webapp_registry_stack import _registry_stack


def test_github_oidc_owns_only_delivery_authority(monkeypatch):
    app_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:yoke/prod/github-app-private-key-AbCdEf"
    )
    recorder, stack = _registry_stack(
        monkeypatch,
        github_repo="upyoke/platform",
        distribution_bucket_names=["upyoke-distribution-prod"],
        cloudfront_distribution_ids=["EPLATFORM"],
        github_app_private_key_secret_arns=[app_secret],
    )

    names = {resource.resource_name for resource in recorder.resources}
    assert (
        not {
            "githubActionsCiRole",
            "githubActionsInfrastructureViewOnly",
            "githubActionsInfrastructureBoundary",
            "githubActionsInfrastructureRoleVariable",
        }
        & names
    )
    assert "githubActionsInfrastructureRoleArn" not in recorder.exports
    assert not hasattr(stack, "infrastructure_role")

    delivery = recorder.single("githubActionsDeliveryRole")
    assert delivery.kwargs["name"] == "yoke-delivery-ci-github"
    subjects = json.loads(delivery.kwargs["assume_role_policy"])["Statement"][0][
        "Condition"
    ]["StringEquals"]["token.actions.githubusercontent.com:sub"]
    assert subjects == [
        "repo:upyoke/platform:ref:refs/heads/main",
        "repo:upyoke/platform:environment:stage",
        "repo:upyoke/platform:environment:prod",
    ]
    policy = json.loads(recorder.single("githubActionsDeliveryPolicy").kwargs["policy"])
    by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
    assert by_sid["DiscoverDistributionIds"] == {
        "Sid": "DiscoverDistributionIds",
        "Effect": "Allow",
        "Action": "cloudfront:ListDistributions",
        "Resource": "*",
    }
    assert by_sid["InvalidateProjectDistributions"]["Resource"] == [
        "arn:aws:cloudfront::123456789012:distribution/EPLATFORM"
    ]
    assert app_secret in by_sid["DenyGitHubAppPrivateKeys"]["Resource"]
    assert recorder.exports["githubActionsDeliveryRoleArn"].value == (
        stack.delivery_role.arn.value
    )

    provider = recorder.single("githubCiRoleVariableProvider")
    assert provider.kwargs == {
        "owner": "upyoke",
        "base_url": "https://api.github.com/",
    }
    variable = recorder.single("githubActionsDeliveryRoleVariable")
    assert variable.kwargs["repository"] == "platform"
    assert variable.kwargs["variable_name"] == "YOKE_DELIVERY_CI_ROLE_ARN"
    assert variable.kwargs["value"].value == stack.delivery_role.arn.value
    assert variable.opts.provider is provider
