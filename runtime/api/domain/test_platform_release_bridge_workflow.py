"""Yoke project releases bridge through scoped hosted GitHub App authority."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "platform-release-bridge.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_bridge_is_project_local_and_correlation_visible() -> None:
    text = _text()

    assert "workflow_dispatch:" in text
    for input_name in (
        "target_environment",
        "release_mode",
        "product_sha",
        "yoke_dispatch_id",
    ):
        assert f"      {input_name}:" in text
    assert "[yoke-dispatch:${{ inputs.yoke_dispatch_id }}]" in text
    assert "permissions:\n  contents: read" in text


def test_bridge_requires_one_annotated_release_tag_for_the_product_sha() -> None:
    text = _text()

    assert '["git", "tag", "--points-at", sha]' in text
    assert '["git", "cat-file", "-t", f"refs/tags/{tag}"]' in text
    assert 'if object_type == "tag"' in text
    assert "product_sha must carry exactly one annotated" in text


def test_bridge_uses_scoped_yoke_api_token_not_cross_repo_github_token() -> None:
    text = _text()

    assert "secrets.YOKE_PLATFORM_RELEASE_API_TOKEN" in text
    assert "yoke github-actions trigger" in text
    assert "upyoke/platform platform-release.yml" in text
    assert "--project platform" in text
    assert "yoke github-actions wait-run" in text
    assert "personal access token" not in text.lower()
    for retired_secret_name in (
        "GH_PAT",
        "CROSS_REPO_TOKEN",
        "YOKE_DEPLOY_PAT",
    ):
        assert retired_secret_name not in text


def test_bridge_forwards_environment_release_mode_and_annotated_tag() -> None:
    text = _text()

    assert '--input "target_environment=$TARGET_ENVIRONMENT"' in text
    assert '--input "product_ref=$PRODUCT_REF"' in text
    assert '--input "release_mode=$RELEASE_MODE"' in text
    assert "--correlation-input yoke_dispatch_id" in text
