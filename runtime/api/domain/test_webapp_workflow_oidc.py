"""OIDC-only AWS authority for reusable webapp delivery workflows."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.project_renderer_values import (
    CONFIGURE_AWS_CREDENTIALS_ACTION,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_NAMES = ("deploy.yml", "hotfix.yml")
STATIC_AWS_SECRET_REFERENCES = (
    "secrets.AWS_ACCESS_KEY_ID",
    "secrets.AWS_SECRET_ACCESS_KEY",
)


def _workflow_text(name: str) -> str:
    return REPO_ROOT.joinpath("templates", "webapp", "ops", name).read_text(
        encoding="utf-8"
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
