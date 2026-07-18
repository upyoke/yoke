"""OIDC-only AWS authority for reusable webapp delivery workflows."""

from __future__ import annotations

from pathlib import Path
import re

from yoke_core.domain import yaml_helper
from yoke_core.domain.project_renderer import render_project
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from yoke_core.domain.project_renderer_values import (
    CONFIGURE_AWS_CREDENTIALS_ACTION,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_ROOT = (
    REPO_ROOT / "packages" / "yoke-core" / "src" / "yoke_core"
    / "install_bundle_tree"
)
WORKFLOW_NAMES = ("deploy.yml", "hotfix.yml")
STATIC_AWS_SECRET_REFERENCES = (
    "secrets.AWS_ACCESS_KEY_ID",
    "secrets.AWS_SECRET_ACCESS_KEY",
)


def _workflow_text(name: str) -> str:
    return REPO_ROOT.joinpath("templates", "webapp", "ops", name).read_text(
        encoding="utf-8"
    )


def _settings() -> ProjectRendererSettings:
    environment = RendererEnvironmentSettings(
        id="acme-production",
        name="production",
        settings={"hosts": {"origin": "origin.example.test"}},
    )
    return ProjectRendererSettings(
        project="acme",
        deploy_namespace="acme",
        display_name="Acme",
        site_id="acme-web",
        site_settings={
            "domains": [{"domain_name": "example.test"}],
            "cdn": {"distribution_id": "EACME123456789"},
        },
        primary_environment=environment,
        environments=(environment,),
        capabilities={
            "aws-admin": {"region": "us-east-2"},
            "ssh": {"default_user": "deploy"},
        },
    )


def test_aws_credentials_action_uses_one_immutable_reviewed_revision() -> None:
    action, revision = CONFIGURE_AWS_CREDENTIALS_ACTION.split("@", 1)
    commit = revision.split(" ", 1)[0]

    assert action == "aws-actions/configure-aws-credentials"
    assert len(commit) == 40
    assert all(character in "0123456789abcdef" for character in commit)


def test_delivery_workflows_assume_oidc_role_and_reject_static_aws_secrets() -> None:
    for name in WORKFLOW_NAMES:
        text = _workflow_text(name)

        assert "permissions:\n  contents: read\n  id-token: write" in text
        assert text.count("uses: {{configure_aws_credentials_action}}") == 1
        assert "role-to-assume: ${{ vars.YOKE_DELIVERY_CI_ROLE_ARN }}" in text
        assert "aws-region: {{aws_region}}" in text
        for secret_reference in STATIC_AWS_SECRET_REFERENCES:
            assert secret_reference not in text
        assert "skipping CloudFront invalidation" not in text


def test_delivery_workflows_fail_closed_with_bounded_cloudfront_diagnostics() -> None:
    for name in WORKFLOW_NAMES:
        text = _workflow_text(name)

        assert "aws cloudfront list-distributions" in text
        assert "aws cloudfront create-invalidation" in text
        assert "CloudFront distribution ID is not configured" in text
        assert "CloudFront distribution discovery failed" in text
        assert "CloudFront invalidation failed" in text
        assert text.count("tail -c 2000") == 2
        assert 'exit "$list_rc"' in text
        assert 'exit "$invalidation_rc"' in text


def test_delivery_workflows_render_valid_oidc_only_yaml_from_both_bundles(
    tmp_path: Path,
) -> None:
    canonical_output = tmp_path / "canonical"
    packaged_output = tmp_path / "packaged"
    settings = _settings()

    render_project(
        "acme",
        write=True,
        only="workflows",
        project_root=REPO_ROOT,
        output_dir=canonical_output,
        settings=settings,
    )
    render_project(
        "acme",
        write=True,
        only="workflows",
        project_root=PACKAGED_ROOT,
        output_dir=packaged_output,
        settings=settings,
    )

    for template_name in WORKFLOW_NAMES:
        rendered_name = f"acme-{template_name}"
        canonical_template = REPO_ROOT / "templates" / "webapp" / "ops" / template_name
        packaged_template = PACKAGED_ROOT / "templates" / "webapp" / "ops" / template_name
        canonical_path = canonical_output / "workflows" / rendered_name
        packaged_path = packaged_output / "workflows" / rendered_name

        assert canonical_template.read_bytes() == packaged_template.read_bytes()
        assert canonical_path.read_bytes() == packaged_path.read_bytes()
        assert isinstance(yaml_helper.load_document(canonical_path), dict)

        text = canonical_path.read_text(encoding="utf-8")
        assert not re.search(r"(?<!\$)\{\{[A-Za-z_]", text)
        assert CONFIGURE_AWS_CREDENTIALS_ACTION in text
        assert "permissions:\n  contents: read\n  id-token: write" in text
        assert "role-to-assume: ${{ vars.YOKE_DELIVERY_CI_ROLE_ARN }}" in text
        assert "CLOUDFRONT_DISTRIBUTION_ID: EACME123456789" in text
        for secret_reference in STATIC_AWS_SECRET_REFERENCES:
            assert secret_reference not in text
