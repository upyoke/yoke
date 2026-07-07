"""GitHub Actions workflow guards for Yoke product distribution."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "yoke-distribution-publish.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_does_not_embed_shell_expansion_as_action() -> None:
    body = _workflow()

    assert "${{YOKE_INSTALL_BASE_URL" not in body
    assert '${{ YOKE_INSTALL_BASE_URL' not in body
    assert 'base_url="${YOKE_INSTALL_BASE_URL:-' in body


def test_workflow_publishes_and_invalidates_the_simple_index() -> None:
    body = _workflow()

    # The mutable simple/ index tree is uploaded short-cache.
    assert 'aws s3 cp "$SIMPLE_DIR' in body
    assert '"s3://$BUCKET/simple"' in body
    assert "--recursive" in body
    # The simple/ index pages are invalidated alongside the other mutable paths.
    assert '"/simple/*"' in body
    assert '"/install"' in body
    assert '"/dist/install.py"' in body
    assert '"/dist/channels/$CHANNEL.json"' in body


def test_workflow_smokes_index_and_records_not_a_manifest() -> None:
    body = _workflow()

    assert '--index-url "$INDEX_URL"' in body
    assert '--release-records "$RELEASE_RECORDS_PATH"' in body
    # The wheelhouse-zip + find-links manifest surfaces are fully gone.
    assert "MANIFEST_PATH" not in body
    assert "WHEELHOUSE" not in body
    assert "wheelhouse" not in body
    assert "yoke-package-index.json" not in body


def test_workflow_keeps_immutable_wheel_bytes_guard_without_cleanup() -> None:
    body = _workflow()

    assert "immutable release object differs" in body
    assert "dist/releases/{version}/" in body
    assert "aws s3 rm" not in body
    assert "s3api delete-object" not in body
    assert "delete-objects" not in body


def test_workflow_has_no_active_homebrew_delivery_path() -> None:
    body = _workflow()

    assert "homebrew" not in body.lower()
    assert "brew " not in body
    assert "YOKE_MACOS_RUNS_ON" not in body
    assert "macos-latest" not in body
    assert "actions/download-artifact" not in body


def test_workflow_uses_commit_time_for_release_build() -> None:
    body = _workflow()

    assert 'release_generated_at="$(git show -s --format=%cI HEAD)"' in body
    assert 'export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"' in body
    assert '--generated-at "$release_generated_at" \\' in body


def test_workflow_defaults_target_env_to_stage() -> None:
    body = _workflow()

    # Both the dispatch input and the shell fallback default to stage;
    # prod is opt-in only.
    assert 'default: "stage"' in body
    assert 'default: "prod"' not in body
    assert 'target_env="${INPUT_TARGET_ENV:-stage}"' in body
    assert "${INPUT_TARGET_ENV:-prod}" not in body


def test_workflow_gates_prod_publish_on_main_ref() -> None:
    body = _workflow()

    assert '[ "$GITHUB_REF_NAME" != "main" ]' in body
    assert (
        "echo \"prod distribution publish requires ref main; "
        "got '$GITHUB_REF_NAME'\" >&2" in body
    )


def test_workflow_pins_source_sha_to_dispatching_ref_history() -> None:
    body = _workflow()

    assert (
        'git fetch --no-tags origin '
        '"+refs/heads/$GITHUB_REF_NAME:refs/remotes/origin/$GITHUB_REF_NAME"'
    ) in body
    assert (
        'git merge-base --is-ancestor "$SOURCE_SHA" "origin/$GITHUB_REF_NAME"'
        in body
    )
    assert (
        "echo \"source_sha '$SOURCE_SHA' is not in the history of "
        "'$GITHUB_REF_NAME'; distribution publishes ship SHAs from the "
        "dispatching ref only\" >&2" in body
    )
    # The ref fetch and ancestry gate both run before the detached checkout.
    checkout_at = body.index('git checkout --detach "$SOURCE_SHA"')
    ancestry_at = body.index("git merge-base --is-ancestor")
    assert body.index("git fetch --no-tags origin") < ancestry_at
    assert ancestry_at < checkout_at


def test_workflow_concurrency_group_keys_on_target_env() -> None:
    body = _workflow()

    assert (
        "group: ${{ github.workflow }}-${{ github.ref }}"
        "-${{ inputs.target_env || 'stage' }}"
    ) in body


def test_workflow_is_reusable_by_stage_deploy() -> None:
    body = _workflow()

    assert "workflow_call:" in body
    assert "workflow_dispatch:" in body
    assert "INPUT_CHANNEL: ${{ inputs.channel }}" in body
    assert "INPUT_TARGET_ENV: ${{ inputs.target_env }}" in body
    assert "SOURCE_SHA: ${{ inputs.source_sha }}" in body


def test_workflow_smokes_stage_installer_base_url() -> None:
    body = _workflow()

    assert 'if [ "${{ steps.target.outputs.target_env }}" = "stage" ]; then' in body
    assert '"$PUBLIC_BASE_URL/install" "$RUNNER_TEMP/yoke-install"' in body
    assert 'YOKE_INSTALL_BASE_URL="$PUBLIC_BASE_URL" YOKE_INSTALL_YES=1' in body
    assert '/bin/sh "$RUNNER_TEMP/yoke-install" --channel "$CHANNEL" --dry-run' in body
