"""OIDC-only AWS authority for reusable webapp delivery workflows."""

from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from yoke_core.domain import pack_catalog
from yoke_core.domain import yaml_helper
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from yoke_core.domain.project_renderer_values import (
    CHECKOUT_ACTION,
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
CLOUDFRONT_HELPER = (
    REPO_ROOT / "packs/domain-cdn-edge/versions/1.0.0/files"
    / "ops/cloudfront_invalidate.py"
)
PACKAGED_CLOUDFRONT_HELPER = (
    PACKAGED_ROOT / "packs/domain-cdn-edge/versions/1.0.0/files"
    / "ops/cloudfront_invalidate.py"
)


def _workflow_text(name: str) -> str:
    return REPO_ROOT.joinpath(
        "packs", "production-deploy", "versions", "1.0.0", "files",
        ".github", "workflows", f"{{{{project_name}}}}-{name}",
    ).read_text(encoding="utf-8")


def _rendered_bundle(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: root)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=1, slug="acme"),
    )
    monkeypatch.setattr(
        pack_catalog, "_load_project_renderer_settings", lambda *args: _settings()
    )
    return pack_catalog.build_pack_bundle(
        object(), project="acme", pack="production-deploy"
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


def test_workflow_actions_use_immutable_reviewed_revisions() -> None:
    expected = {
        CHECKOUT_ACTION: "actions/checkout",
        CONFIGURE_AWS_CREDENTIALS_ACTION: "aws-actions/configure-aws-credentials",
    }
    for action_ref, expected_action in expected.items():
        action, revision = action_ref.split("@", 1)
        commit = revision.split(" ", 1)[0]

        assert action == expected_action
        assert len(commit) == 40
        assert all(character in "0123456789abcdef" for character in commit)


def test_delivery_workflows_assume_oidc_role_and_reject_static_aws_secrets() -> None:
    for name in WORKFLOW_NAMES:
        text = _workflow_text(name)

        assert "permissions:\n  contents: read\n  id-token: write" in text
        assert text.count("uses: {{checkout_action}}") == 1
        assert text.count("uses: {{configure_aws_credentials_action}}") == 1
        assert "role-to-assume: ${{ vars.YOKE_DELIVERY_CI_ROLE_ARN }}" in text
        assert "aws-region: {{aws_region}}" in text
        assert "role-session-name: {{project_name}}-" in text
        for secret_reference in STATIC_AWS_SECRET_REFERENCES:
            assert secret_reference not in text
        assert "skipping CloudFront invalidation" not in text


def test_delivery_workflows_call_pack_installed_cloudfront_helper() -> None:
    for name in WORKFLOW_NAMES:
        text = _workflow_text(name)

        assert (
            'python3 ops/cloudfront_invalidate.py "$CLOUDFRONT_DISTRIBUTION_ID"'
            in text
        )


def test_cloudfront_helper_is_mirrored_and_bounds_failure_diagnostics() -> None:
    helper = CLOUDFRONT_HELPER.read_text(encoding="utf-8")

    assert CLOUDFRONT_HELPER.read_bytes() == PACKAGED_CLOUDFRONT_HELPER.read_bytes()
    assert '"list-distributions"' in helper
    assert '"create-invalidation"' in helper
    assert "CloudFront distribution ID is not configured" in helper
    assert "CloudFront distribution discovery failed" in helper
    assert "CloudFront invalidation failed" in helper
    assert "MAX_DIAGNOSTIC_CHARS = 2000" in helper
    assert "output[-MAX_DIAGNOSTIC_CHARS:]" in helper


def test_delivery_workflows_render_valid_oidc_only_yaml_from_both_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _rendered_bundle(REPO_ROOT, monkeypatch)
    packaged = _rendered_bundle(PACKAGED_ROOT, monkeypatch)
    canonical_files = {row["path"]: row for row in canonical["files"]}
    packaged_files = {row["path"]: row for row in packaged["files"]}

    for source_name in WORKFLOW_NAMES:
        rendered_name = f".github/workflows/acme-{source_name}"
        canonical_path = tmp_path / source_name
        canonical_path.write_text(canonical_files[rendered_name]["content"])
        assert canonical_files[rendered_name] == packaged_files[rendered_name]
        assert isinstance(yaml_helper.load_document(canonical_path), dict)

        text = canonical_path.read_text(encoding="utf-8")
        assert not re.search(r"(?<!\$)\{\{[A-Za-z_]", text)
        assert CHECKOUT_ACTION in text
        assert CONFIGURE_AWS_CREDENTIALS_ACTION in text
        assert "permissions:\n  contents: read\n  id-token: write" in text
        assert "role-to-assume: ${{ vars.YOKE_DELIVERY_CI_ROLE_ARN }}" in text
        assert "CLOUDFRONT_DISTRIBUTION_ID: EACME123456789" in text
        for secret_reference in STATIC_AWS_SECRET_REFERENCES:
            assert secret_reference not in text
