"""Yoke project releases bridge through scoped hosted GitHub App authority."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "platform-release-bridge.yml"


def _platform_workflow() -> Path:
    projects_root = ROOT.parents[2] if ROOT.parent.name == ".worktrees" else ROOT.parent
    return projects_root / "platform" / ".github" / "workflows" / "yoke-release-promote.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_bridge_is_project_local_and_correlation_visible() -> None:
    text = _text()

    assert "workflow_dispatch:" in text
    for input_name in (
        "target_environment",
        "release_mode",
        "product_sha",
        "deployment_run_id",
        "yoke_dispatch_id",
    ):
        assert f"      {input_name}:" in text
    assert "[yoke-dispatch:${{ inputs.yoke_dispatch_id }}]" in text
    assert "permissions:\n  actions: read\n  contents: read" in text


def test_bridge_creates_or_recovers_one_annotated_release_tag() -> None:
    text = _text()

    assert "yoke github release create-next-tag" in text
    assert 'upyoke/yoke "$PRODUCT_SHA"' in text
    assert "secrets.YOKE_RELEASE_API_TOKEN" in text
    assert "yoke-release.yml yoke-server-image.yml" in text
    assert "yoke github-actions find-run" in text


def test_bridge_uses_scoped_yoke_api_token_not_cross_repo_github_token() -> None:
    text = _text()

    assert "secrets.YOKE_PLATFORM_RELEASE_API_TOKEN" in text
    assert "yoke github-actions trigger" in text
    assert "upyoke/platform yoke-release-promote.yml" in text
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


def test_bridge_carries_the_registered_environment_name_not_a_promotion_label() -> None:
    declared = _text().split("      target_environment:", 1)[1].split(
        "      release_mode:", 1
    )[0]

    assert "          - stage\n          - prod\n" in declared
    assert "platform_target" not in declared


def test_bridge_passes_the_registered_environment_name_to_the_platform_dispatch() -> None:
    text = _text()
    dispatch = text.split(
        "- name: Dispatch and await Platform pin promotion and release", 1
    )[1].split("      - name: ", 1)[0]

    # Platform's promotion train is keyed by the registered environment
    # names, so the bridge passes the name through unchanged and never
    # reintroduces a translated promotion label.
    assert 'case "$TARGET_ENVIRONMENT" in' in dispatch
    assert "stage|prod) ;;" in dispatch
    assert '--input "target_environment=$TARGET_ENVIRONMENT"' in dispatch
    assert "platform_target" not in dispatch
    assert "production" not in dispatch
    # An unroutable environment stops the release rather than dispatching a
    # promotion input Platform's own choice list would reject.
    assert "no Platform promotion route for environment $TARGET_ENVIRONMENT" in dispatch


def test_bridge_hands_yoke_surfaces_the_registered_environment_name() -> None:
    text = _text()
    preflight = text.split(
        "- name: Refuse a release carrying an unrehearsed migration entry", 1
    )[1].split("      - name: ", 1)[0]
    record = text.split(
        "- name: Record desired pin after successful Platform release", 1
    )[1]

    for step in (preflight, record):
        assert "TARGET_ENVIRONMENT: ${{ inputs.target_environment }}" in step
        assert "platform_target" not in step
    assert '"$TARGET_ENVIRONMENT" "$PRODUCT_SHA"' in preflight
    assert '--environment "$TARGET_ENVIRONMENT"' in record


def test_bridge_recovers_a_lost_dispatch_response_without_reposting() -> None:
    text = _text()

    assert "for attempt in $(seq 1 12)" in text
    assert 'request_id="bridge:${GITHUB_RUN_ID}:${GITHUB_RUN_ATTEMPT}:' in text
    assert '--request-id "$request_id"' in text
    assert 'grep -q "workflow_dispatch_ambiguous"' in text
    assert "same scoped actor" in text
    assert 'test -n "$platform_run_id"' in text


def test_bridge_records_pin_only_after_terminal_platform_success() -> None:
    text = _text()
    authority_marker = "- name: Switch to scoped Platform promotion authority"
    record_marker = "- name: Record desired pin after successful Platform release"
    record = text.split(record_marker, 1)[1]

    assert text.index(authority_marker) < text.index(record_marker)
    assert text.rindex("yoke github-actions wait-run") < text.index(record_marker)
    assert text.count("yoke release-pin record") == 1
    assert 'VERSION="${PRODUCT_REF#v}"' in record
    assert 'receipt="$(yoke release-pin record \\' in record
    assert "--project platform" in record
    assert '--environment "$TARGET_ENVIRONMENT"' in record
    assert '--pin "$VERSION"' in record
    assert 'test -n "$receipt"' in record
    assert "continue-on-error" not in record
    assert text.rstrip().endswith('echo "Desired release pin receipt: $receipt"')


def test_bridge_writer_accepts_no_environment_id_or_settings_path() -> None:
    record = _text().split(
        "- name: Record desired pin after successful Platform release", 1
    )[1]

    assert "environment-settings merge" not in record
    assert "--environment-id" not in record
    assert "desired_pin_path" not in record
    assert "release.yoke_pin" not in record
    assert "yoke-api-stage" not in record
    assert "yoke-api-prod" not in record


def test_cross_repo_workflows_have_one_narrow_release_pin_writer() -> None:
    platform_workflow_path = _platform_workflow()
    if not platform_workflow_path.exists():
        pytest.skip("sibling Platform checkout is not available")
    yoke_workflow = _text()
    platform_workflow = platform_workflow_path.read_text(encoding="utf-8")

    assert yoke_workflow.count("yoke release-pin record") == 1
    for forbidden in (
        "record-desired-pin:",
        "yoke release-pin record",
        "projects environment-settings merge",
        "YOKE_INFRA_API_TOKEN",
        "YOKE_DEPLOY_API_TOKEN",
    ):
        assert forbidden not in platform_workflow
