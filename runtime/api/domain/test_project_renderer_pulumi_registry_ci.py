"""Registry-stack GitHub CI federation: template render + trust contract.

The Pulumi program is not importable in the test env (pulumi/pulumi_aws
are deploy-time deps), so the trust-policy contract is checked by
exec'ing the pure policy builder out of the template source via AST —
the same boundary style as the entrypoint import test.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import runpy

from yoke_core.domain.project_renderer_pulumi import render_pulumi_stack_yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _registry_stack_source() -> str:
    return _repo_root().joinpath(
        "templates", "webapp", "infra", "webapp_registry_stack.py",
    ).read_text()


def _exec_pure_policy_builder():
    """Exec only the policy constants + builder (no pulumi imports)."""
    tree = ast.parse(_registry_stack_source())
    wanted: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                t.id for t in node.targets if isinstance(t, ast.Name)
            }
            if names & {"_GITHUB_OIDC_HOST", "_GITHUB_OIDC_THUMBPRINTS"}:
                wanted.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "_github_trust_policy_json":
            wanted.append(node)
    namespace: dict = {"json": json}
    exec(  # noqa: S102 — template source under test, no external input
        compile(ast.Module(body=wanted, type_ignores=[]), "<registry>", "exec"),
        namespace,
    )
    return namespace


class TestGithubTrustPolicy:
    def test_policy_scopes_to_exactly_the_repo(self):
        ns = _exec_pure_policy_builder()
        policy = json.loads(
            ns["_github_trust_policy_json"](
                "arn:aws:iam::123456789012:oidc-provider/"
                "token.actions.githubusercontent.com",
                "acme-org/acme",
                ("main",),
            )
        )
        (statement,) = policy["Statement"]
        assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
        assert statement["Principal"]["Federated"].endswith(
            "oidc-provider/token.actions.githubusercontent.com"
        )
        condition = statement["Condition"]
        assert condition["StringEquals"] == {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": [
                "repo:acme-org/acme:ref:refs/heads/main"
            ],
        }
        assert "StringLike" not in condition

    def test_feature_and_pull_request_subjects_are_not_trusted(self):
        ns = _exec_pure_policy_builder()
        policy = json.loads(ns["_github_trust_policy_json"](
            "arn:aws:iam::123456789012:oidc-provider/"
            "token.actions.githubusercontent.com",
            "acme-org/acme",
            ("main", "stage"),
        ))
        subjects = policy["Statement"][0]["Condition"]["StringEquals"][
            "token.actions.githubusercontent.com:sub"
        ]
        assert "repo:acme-org/acme:ref:refs/heads/main" in subjects
        assert "repo:acme-org/acme:ref:refs/heads/stage" in subjects
        assert all("pull_request" not in subject for subject in subjects)
        assert all("feature" not in subject for subject in subjects)

    def test_thumbprint_list_is_nonempty(self):
        ns = _exec_pure_policy_builder()
        assert ns["_GITHUB_OIDC_THUMBPRINTS"], (
            "IAM requires at least one thumbprint at provider create time"
        )


class TestRegistryProgramShape:
    def test_no_static_credential_teaching(self):
        source = _registry_stack_source()
        assert "AccessKey" not in source, (
            "the registry stack must never mint static access keys for CI"
        )

    def test_infrastructure_and_delivery_roles_are_separate(self):
        source = _registry_stack_source()
        assert "AdministratorAccess" not in source
        assert "job-function/ViewOnlyAccess" in source
        assert "githubActionsInfrastructureRoleArn" in source
        assert "githubActionsDeliveryRoleArn" in source
        assert "githubActionsDeliveryPolicy" in source

    def test_preview_policy_denies_privilege_and_secret_escalation(
        self, monkeypatch,
    ):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        monkeypatch.syspath_prepend(str(path.parent))
        policy = json.loads(runpy.run_path(path)[
            "infrastructure_preview_policy_json"
        ](
            region="us-east-1",
            account_id="123456789012",
            state_bucket="yoke-pulumi-state",
            kms_key_arn=(
                "arn:aws:kms:us-east-1:123456789012:key/state-key"
            ),
            deploy_namespace="yoke",
            distribution_bucket_names=["upyoke-distribution-prod"],
            github_app_private_key_secret_arns=[],
        ))
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
            "s3:GetBucketPolicy",
            "cloudfront:GetDistribution",
            "lambda:GetFunction",
            "rds:Describe*",
        }.issubset(allowed_actions)
        assert not any(action.startswith("iam:Create") for action in allowed_actions)
        assert "iam:PassRole" not in allowed_actions
        assert not any(action.startswith("organizations:") for action in allowed_actions)
        assert "sts:AssumeRole" not in allowed_actions
        privilege_deny = next(
            statement for statement in statements
            if statement["Sid"] == "DenyPrivilegeEscalation"
        )
        assert "iam:PassRole" in privilege_deny["Action"]
        assert "organizations:*" in privilege_deny["Action"]
        assert "sts:AssumeRole" in privilege_deny["Action"]
        secret_deny = next(
            statement for statement in statements
            if statement["Sid"] == "DenySecretValues"
        )
        assert secret_deny["Resource"] == "*"
        object_deny = next(
            statement for statement in statements
            if statement["Sid"] == "DenyNonStateObjectReads"
        )
        assert object_deny["NotResource"] == (
            "arn:aws:s3:::yoke-pulumi-state/.pulumi/*"
        )
        parameter_deny = next(
            statement for statement in statements
            if statement["Sid"] == "DenyNonPublicParameterValues"
        )
        assert "ssm:GetParametersByPath" in parameter_deny["Action"]

    def test_delivery_policy_denies_app_keys_and_scopes_delivery(self):
        path = _repo_root().joinpath(
            "templates", "webapp", "infra", "webapp_registry_ci_policy.py"
        )
        policy = json.loads(runpy.run_path(path)["delivery_policy_json"](
            region="us-east-1",
            account_id="123456789012",
            deploy_namespace="yoke",
            state_bucket="yoke-pulumi-state",
            kms_key_arn=(
                "arn:aws:kms:us-east-1:123456789012:key/state-key"
            ),
            distribution_bucket_names=["upyoke-distribution-prod"],
            github_app_private_key_secret_arns=[
                "arn:aws:secretsmanager:us-east-1:123456789012:"
                "secret:yoke/prod/github-app-private-key-AbCdEf"
            ],
        ))
        by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
        assert by_sid["ProjectImageDelivery"]["Resource"] == (
            "arn:aws:ecr:us-east-1:123456789012:repository/yoke-*"
        )
        assert by_sid["ReadRdsManagedDatabaseCredentials"]["Resource"].endswith(
            "secret:rds!cluster-*"
        )
        assert by_sid["ReadRdsManagedDatabaseCredentials"]["Condition"] == {
            "StringEquals": {
                "secretsmanager:ResourceTag/"
                "aws:secretsmanager:owningService": "rds",
            },
            "StringLike": {
                "secretsmanager:ResourceTag/"
                "aws:rds:primaryDBClusterArn": (
                    "arn:aws:rds:us-east-1:123456789012:"
                    "cluster:yoke-*-aurora"
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
        assert by_sid["PublishDistributionArtifacts"]["Resource"] == [
            "arn:aws:s3:::upyoke-distribution-prod/*"
        ]
        assert by_sid["InvalidateProjectDistributions"]["Action"] == (
            "cloudfront:CreateInvalidation"
        )
        deny = by_sid["DenyGitHubAppPrivateKeys"]
        assert deny["Effect"] == "Deny"
        assert any("github-app-private-key" in arn for arn in deny["Resource"])
        assert "AdministratorAccess" not in json.dumps(policy)


class TestRegistryTemplateRender:
    def test_real_registry_template_renders_ci_keys(self, tmp_path):
        template = _repo_root().joinpath(
            "templates", "webapp", "infra", "Pulumi.registry-stack.yaml.tmpl",
        )
        rendered = render_pulumi_stack_yaml(template, {
            "aws_region": "us-east-1",
            "aws_account_id": "123456789012",
            "deploy_namespace": "acme",
            "repository_name": "acme-core",
            "github_repo_slug": "acme-org/acme",
            "github_api_url": "https://api.github.com",
            "manage_github_oidc_provider": "true",
            "state_bucket": "acme-pulumi-state",
            "kms_key_alias": "alias/acme-pulumi-state",
            "delivery_distribution_bucket_names_json": (
                '["acme-distribution-prod"]'
            ),
            "github_app_private_key_secret_arns_json": (
                '["arn:aws:secretsmanager:us-east-1:123456789012:'
                'secret:acme/prod/github-app-private-key-AbCdEf"]'
            ),
        })
        assert "webapp-infra:github_repo: acme-org/acme" in rendered
        assert "webapp-infra:github_api_url: https://api.github.com" in rendered
        assert 'webapp-infra:manage_github_oidc_provider: "true"' in rendered
        assert "webapp-infra:distribution_bucket_names:" in rendered
        assert "webapp-infra:github_app_private_key_secret_arns:" in rendered
        assert "{{" not in rendered
