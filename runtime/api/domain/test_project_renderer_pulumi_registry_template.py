"""Registry-stack template, trust-policy, and program-shape coverage."""

import ast
import json

from yoke_core.domain.project_renderer_pulumi import render_pulumi_stack_yaml
from runtime.api.domain.test_project_renderer_pulumi_registry_ci import _repo_root


def _registry_stack_source() -> str:
    return (
        _repo_root()
        .joinpath(
            "templates",
            "webapp",
            "infra",
            "webapp_registry_stack.py",
        )
        .read_text()
    )


def _exec_pure_policy_builder():
    """Exec only the policy constants + builder (no pulumi imports)."""
    tree = ast.parse(_registry_stack_source())
    wanted: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if names & {"_GITHUB_OIDC_HOST", "_GITHUB_OIDC_THUMBPRINTS"}:
                wanted.append(node)
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_github_trust_policy_json"
        ):
            wanted.append(node)
    namespace: dict = {"json": json}
    exec(  # noqa: S102 — template source under test, no external input
        compile(ast.Module(body=wanted, type_ignores=[]), "<registry>", "exec"),
        namespace,
    )
    return namespace


class TestGithubTrustPolicy:
    def test_policy_scopes_to_exactly_the_repo(self):
        namespace = _exec_pure_policy_builder()
        policy = json.loads(
            namespace["_github_trust_policy_json"](
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
        namespace = _exec_pure_policy_builder()
        policy = json.loads(
            namespace["_github_trust_policy_json"](
                "arn:aws:iam::123456789012:oidc-provider/"
                "token.actions.githubusercontent.com",
                "acme-org/acme",
                ("main", "stage"),
            )
        )
        subjects = policy["Statement"][0]["Condition"]["StringEquals"][
            "token.actions.githubusercontent.com:sub"
        ]
        assert "repo:acme-org/acme:ref:refs/heads/main" in subjects
        assert "repo:acme-org/acme:ref:refs/heads/stage" in subjects
        assert all("pull_request" not in subject for subject in subjects)
        assert all("feature" not in subject for subject in subjects)

    def test_thumbprint_list_is_nonempty(self):
        namespace = _exec_pure_policy_builder()
        assert namespace["_GITHUB_OIDC_THUMBPRINTS"], (
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


def test_real_registry_template_renders_ci_keys():
    template = _repo_root().joinpath(
        "templates",
        "webapp",
        "infra",
        "Pulumi.registry-stack.yaml.tmpl",
    )
    rendered = render_pulumi_stack_yaml(
        template,
        {
            "aws_region": "us-east-1",
            "aws_account_id": "123456789012",
            "deploy_namespace": "acme",
            "repository_name": "acme-core",
            "github_repo_slug": "acme-org/acme",
            "github_api_url": "https://api.github.com",
            "manage_github_oidc_provider": "true",
            "state_bucket": "acme-pulumi-state",
            "kms_key_alias": "alias/acme-pulumi-state",
            "delivery_distribution_bucket_names_json": ('["acme-distribution-prod"]'),
            "github_app_private_key_secret_arns_json": (
                '["arn:aws:secretsmanager:us-east-1:123456789012:'
                'secret:acme/prod/github-app-private-key-AbCdEf"]'
            ),
        },
    )
    assert "webapp-infra:github_repo: acme-org/acme" in rendered
    assert "webapp-infra:github_api_url: https://api.github.com" in rendered
    assert 'webapp-infra:manage_github_oidc_provider: "true"' in rendered
    assert "webapp-infra:distribution_bucket_names:" in rendered
    assert "webapp-infra:github_app_private_key_secret_arns:" in rendered
    assert "{{" not in rendered
