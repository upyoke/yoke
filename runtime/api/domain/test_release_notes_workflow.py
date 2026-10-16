"""Executable public-release and immutable tag-note workflow contract."""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "yoke-release.yml"
_DOC = _ROOT / "docs" / "releases" / "README.md"


def _text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_only_version_tag_pushes_trigger_release():
    text = _text()
    trigger = text[text.index("on:\n") : text.index("\nconcurrency:")]
    assert "push:" in trigger
    assert '      - "[0-9]*"' in trigger
    assert "pull_request" not in trigger
    assert "workflow_dispatch" not in trigger
    assert "branches:" not in trigger


def test_release_authority_is_isolated_to_final_hosted_job():
    text = _text()
    assert "permissions: {}" in text
    assert text.count("contents: write") == 1
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert not re.findall(r"secrets\.([A-Za-z_0-9]+)", text)
    assert re.findall(r"^\s+runs-on:\s*(.+)$", text, re.MULTILINE) == [
        "ubuntu-latest",
        "ubuntu-latest",
    ]
    assert "runs-on: self-hosted" not in text
    assert "YOKE_LINUX_RUNS_ON" not in text


def test_tag_must_have_local_version_exact_commit_and_tag_notes():
    text = _text()
    assert "release_tag_validation.py --require-note-heading" in text
    assert "ref: ${{ github.sha }}" in text
    assert "persist-credentials: false" in text
    assert text.count("git/ref/tags/$TAG_NAME") == 1
    assert text.count("git/tags/$tag_object_sha") == 1
    assert '[[ "$object_type" != "tag"' in text
    assert '[[ "$target_type" != "commit"' in text
    assert '"$source_sha" != "$GITHUB_SHA"' in text
    assert "compare/$source_sha...main" not in text
    assert "docs/releases/$TAG_NAME.md" not in text


def test_release_promotes_main_factory_without_build_or_signing_authority():
    text = _text()
    assert "uses: ./.github/workflows/yoke-build-artifacts.yml" not in text
    assert "  build:" not in text
    release = text[text.index("  release:\n") :]
    assert "needs: validate-tag" in release
    assert "actions: read" in release
    assert "attestations: read" in release
    assert "attestations: write" not in text
    assert "id-token: write" not in text
    assert "secrets: inherit" not in text
    assert "promote_main_artifacts.py wheels" in release
    assert '--source-sha "$GITHUB_SHA"' in release
    assert '--version "$RELEASE_VERSION"' in release


def test_transferred_wheels_are_reverified_by_publication_helper():
    helper = (
        _ROOT / "packages/yoke-core/src/yoke_core/tools/promote_main_artifacts.py"
    ).read_text()
    assert '"release-records.json"' in helper
    assert 'root / "wheels"' in helper
    assert "hashlib.sha256" in helper
    assert 'len(content) != record["size"]' in helper
    assert '"--signer-workflow"' in helper
    assert 'f"{repo}/.github/workflows/{workflow}"' in helper
    assert '"--source-ref",\n        "refs/heads/main"' in helper
    assert '"--source-digest",\n        source' in helper
    assert '"--deny-self-hosted-runners"' in helper
    assert '"yoke-build-artifacts.yml"' in helper


def test_release_creation_uses_tag_notes_and_validated_assets():
    text = _text()
    verify_index = text.index("Promote verified main-push wheel bytes")
    remote_check_index = text.index(
        "Re-resolve the tag and create the GitHub Release entry"
    )
    create_index = text.index("gh release create")
    assert verify_index < remote_check_index < create_index
    assert "EXPECTED_SOURCE_SHA: ${{ needs.validate-tag.outputs.source_sha }}" in text
    assert (
        "EXPECTED_TAG_OBJECT_SHA: "
        "${{ needs.validate-tag.outputs.tag_object_sha }}" in text
    )
    assert '"$tag_object_sha" != "$EXPECTED_TAG_OBJECT_SHA"' in text
    assert '"$source_sha" != "$EXPECTED_SOURCE_SHA"' in text
    assert 'wheels=("$ARTIFACT_DIR"/wheels/*.whl)' in text
    assert '"${wheels[@]}"' in text
    assert '"$ARTIFACT_DIR/release-records.json"' in text
    assert "--verify-tag" in text
    assert 'jq -r \'.message // ""\' <<< "$tag_object"' in text
    assert '--notes-file "$release_notes"' in text


def test_release_creation_retries_only_http_server_errors():
    release_step = _text().split(
        "- name: Re-resolve the tag and create the GitHub Release entry", 1
    )[1]

    assert "for attempt in 1 2 3" in release_step
    assert "HTTP 5[0-9]{2}([^0-9]|$)" in release_step
    assert 'sleep "$backoff_seconds"' in release_step
    assert "github_release_create_non_retryable" in release_step
    assert "github_release_create_5xx_exhausted" in release_step


def test_public_operator_doc_teaches_current_release_and_verification():
    text = _DOC.read_text(encoding="utf-8")
    assert "source-dev release rules](../source-dev-doctrine.md)" in text
    source_rules = (_ROOT / "docs/source-dev-doctrine.md").read_text()
    assert "yoke-hosted-production-release-qa" in source_rules
    assert "Treat release tags as immutable" in text
    assert "gh attestation verify ./yoke_core-*.whl" in text
    assert "oci://ghcr.io/upyoke/yoke-server@sha256:<digest>" in text
    assert '--source-ref "$release_ref"' in text
    assert text.count("--source-ref refs/heads/main") == 2
    assert text.count("--source-digest") == 3
    assert "--deny-self-hosted-runners" in text
    contributing = (_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "[docs/releases/README.md](docs/releases/README.md)" in contributing
