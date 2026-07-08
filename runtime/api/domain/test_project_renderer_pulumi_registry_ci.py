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
        }
        assert condition["StringLike"] == {
            "token.actions.githubusercontent.com:sub": "repo:acme-org/acme:*",
        }

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

    def test_admin_attachment_is_the_named_tightening_point(self):
        source = _registry_stack_source()
        assert "arn:aws:iam::aws:policy/AdministratorAccess" in source
        assert "tightening point" in source


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
            "manage_github_oidc_provider": "true",
        })
        assert "webapp-infra:github_repo: acme-org/acme" in rendered
        assert 'webapp-infra:manage_github_oidc_provider: "true"' in rendered
        assert "{{" not in rendered
