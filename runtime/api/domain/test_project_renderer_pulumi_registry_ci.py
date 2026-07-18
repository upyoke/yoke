"""Least-privilege policy coverage for registry-stack GitHub CI roles."""

from __future__ import annotations

import json
from pathlib import Path
import runpy


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class TestRegistryProgramShape:
    def test_preview_policy_denies_privilege_and_secret_escalation(
        self,
        monkeypatch,
    ):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        monkeypatch.syspath_prepend(str(path.parent))
        policy = json.loads(
            runpy.run_path(path)["infrastructure_preview_policy_json"](
                region="us-east-1",
                account_id="123456789012",
                state_bucket="yoke-pulumi-state",
                kms_key_arn=("arn:aws:kms:us-east-1:123456789012:key/state-key"),
                deploy_namespace="yoke",
                distribution_bucket_names=["upyoke-distribution-prod"],
                github_app_private_key_secret_arns=[],
            )
        )
        statements = policy["Statement"]
        allowed_actions = {
            action
            for statement in statements
            if statement["Effect"] == "Allow"
            for action in (
                statement["Action"]
                if isinstance(statement["Action"], list)
                else [statement["Action"]]
            )
        }
        assert {
            "ec2:Describe*",
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:GetOpenIDConnectProvider",
            "kms:ListAliases",
            "s3:GetBucketPolicy",
            "cloudfront:GetDistribution",
            "lambda:GetFunction",
            "rds:Describe*",
        }.issubset(allowed_actions)
        assert not any(action.startswith("iam:Create") for action in allowed_actions)
        assert "iam:PassRole" not in allowed_actions
        assert not any(
            action.startswith("organizations:") for action in allowed_actions
        )
        assert "sts:AssumeRole" not in allowed_actions
        privilege_deny = next(
            statement
            for statement in statements
            if statement["Sid"] == "DenyPrivilegeEscalation"
        )
        assert "iam:PassRole" in privilege_deny["Action"]
        assert "organizations:*" in privilege_deny["Action"]
        assert "sts:AssumeRole" in privilege_deny["Action"]
        secret_deny = next(
            statement
            for statement in statements
            if statement["Sid"] == "DenySecretValues"
        )
        assert secret_deny["Resource"] == "*"
        object_deny = next(
            statement
            for statement in statements
            if statement["Sid"] == "DenyNonStateObjectReads"
        )
        assert object_deny["NotResource"] == (
            "arn:aws:s3:::yoke-pulumi-state/.pulumi/*"
        )
        parameter_deny = next(
            statement
            for statement in statements
            if statement["Sid"] == "DenyNonPublicParameterValues"
        )
        assert "ssm:GetParametersByPath" in parameter_deny["Action"]

    def test_delivery_policy_denies_app_keys_and_scopes_delivery(self):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        policy = json.loads(
            runpy.run_path(path)["delivery_policy_json"](
                region="us-east-1",
                account_id="123456789012",
                deploy_namespace="yoke",
                state_bucket="yoke-pulumi-state",
                kms_key_arn=("arn:aws:kms:us-east-1:123456789012:key/state-key"),
                distribution_bucket_names=["upyoke-distribution-prod"],
                cloudfront_distribution_ids=["EDISTRIBUTION"],
                github_app_private_key_secret_arns=[
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:yoke/prod/github-app-private-key-AbCdEf"
                ],
            )
        )
        by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
        assert by_sid["ProjectImageDelivery"]["Resource"] == (
            "arn:aws:ecr:us-east-1:123456789012:repository/yoke-*"
        )
        assert by_sid["ReadRdsManagedDatabaseCredentials"]["Resource"].endswith(
            "secret:rds!cluster-*"
        )
        assert by_sid["ReadRdsManagedDatabaseCredentials"]["Condition"] == {
            "StringEquals": {
                "secretsmanager:ResourceTag/aws:secretsmanager:owningService": "rds",
            },
            "StringLike": {
                "secretsmanager:ResourceTag/aws:rds:primaryDBClusterArn": (
                    "arn:aws:rds:us-east-1:123456789012:cluster:yoke-*-aurora"
                ),
            },
        }
        assert by_sid["DiscoverProjectOrigins"] == {
            "Sid": "DiscoverProjectOrigins",
            "Effect": "Allow",
            "Action": "ec2:DescribeInstances",
            "Resource": "*",
        }
        assert by_sid["StartProjectOrigins"]["Condition"] == {
            "StringEquals": {"aws:ResourceTag/project": "yoke"}
        }
        assert by_sid["ReadPulumiStateBucketLocation"]["Resource"] == (
            "arn:aws:s3:::yoke-pulumi-state"
        )
        assert by_sid["ReadPulumiStateBucketLocation"]["Action"] == (
            "s3:GetBucketLocation"
        )
        assert by_sid["ListPulumiState"]["Condition"] == {
            "StringLike": {"s3:prefix": [".pulumi", ".pulumi/*"]}
        }
        assert by_sid["ReadPulumiStateObjects"]["Resource"] == (
            "arn:aws:s3:::yoke-pulumi-state/.pulumi/*"
        )
        assert by_sid["DecryptPulumiStateDataKey"] == {
            "Sid": "DecryptPulumiStateDataKey",
            "Effect": "Allow",
            "Action": ["kms:Decrypt", "kms:DescribeKey"],
            "Resource": "arn:aws:kms:us-east-1:123456789012:key/state-key",
        }
        assert all(
            "kms:ListAliases"
            not in (
                statement["Action"]
                if isinstance(statement["Action"], list)
                else [statement["Action"]]
            )
            for statement in policy["Statement"]
        )
        assert by_sid["PublishDistributionArtifacts"]["Resource"] == [
            "arn:aws:s3:::upyoke-distribution-prod/*"
        ]
        assert by_sid["DiscoverDistributionIds"] == {
            "Sid": "DiscoverDistributionIds",
            "Effect": "Allow",
            "Action": "cloudfront:ListDistributions",
            "Resource": "*",
        }
        assert by_sid["InvalidateProjectDistributions"]["Action"] == (
            "cloudfront:CreateInvalidation"
        )
        assert by_sid["InvalidateProjectDistributions"]["Resource"] == [
            "arn:aws:cloudfront::123456789012:distribution/EDISTRIBUTION"
        ]
        cloudfront_actions = {
            action
            for statement in policy["Statement"]
            for action in (
                statement["Action"]
                if isinstance(statement["Action"], list)
                else [statement["Action"]]
            )
            if action.startswith("cloudfront:")
        }
        assert cloudfront_actions == {
            "cloudfront:CreateInvalidation",
            "cloudfront:ListDistributions",
        }
        deny = by_sid["DenyGitHubAppPrivateKeys"]
        assert deny["Effect"] == "Deny"
        assert any("github-app-private-key" in arn for arn in deny["Resource"])
        assert "AdministratorAccess" not in json.dumps(policy)

    def test_delivery_policy_omits_cloudfront_access_without_distribution(self):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        policy = json.loads(
            runpy.run_path(path)["delivery_policy_json"](
                region="us-east-1",
                account_id="123456789012",
                deploy_namespace="yoke",
                state_bucket="yoke-pulumi-state",
                kms_key_arn=("arn:aws:kms:us-east-1:123456789012:key/state-key"),
                distribution_bucket_names=[],
                cloudfront_distribution_ids=[],
                github_app_private_key_secret_arns=[],
            )
        )

        cloudfront_actions = {
            action
            for statement in policy["Statement"]
            for action in (
                statement["Action"]
                if isinstance(statement["Action"], list)
                else [statement["Action"]]
            )
            if action.startswith("cloudfront:")
        }
        assert cloudfront_actions == set()

    def test_delivery_policy_keeps_bucket_access_without_cloudfront_wildcard(self):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        policy = json.loads(
            runpy.run_path(path)["delivery_policy_json"](
                region="us-east-1",
                account_id="123456789012",
                deploy_namespace="buzz",
                state_bucket="buzz-pulumi-state",
                kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/state-key",
                distribution_bucket_names=["buzz-distribution-prod"],
                cloudfront_distribution_ids=[],
                github_app_private_key_secret_arns=[],
            )
        )

        by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
        assert by_sid["PublishDistributionArtifacts"]["Resource"] == [
            "arn:aws:s3:::buzz-distribution-prod/*"
        ]
        assert "DiscoverDistributionIds" not in by_sid
        assert "InvalidateProjectDistributions" not in by_sid
        assert "arn:aws:cloudfront::123456789012:distribution/*" not in json.dumps(
            policy
        )

    def test_delivery_policy_allows_exact_cloudfront_without_distribution_bucket(
        self,
    ):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        policy = json.loads(
            runpy.run_path(path)["delivery_policy_json"](
                region="us-east-1",
                account_id="123456789012",
                deploy_namespace="externalwebapp",
                state_bucket="externalwebapp-pulumi-state",
                kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/state-key",
                distribution_bucket_names=[],
                cloudfront_distribution_ids=["EEXT"],
                github_app_private_key_secret_arns=[],
            )
        )

        by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
        assert by_sid["DiscoverDistributionIds"]["Resource"] == "*"
        assert by_sid["InvalidateProjectDistributions"]["Resource"] == [
            "arn:aws:cloudfront::123456789012:distribution/EEXT"
        ]
