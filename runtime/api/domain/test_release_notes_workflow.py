"""Executable public-release and authored-note workflow contract."""

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
    assert '      - "v*"' in trigger
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


def test_tag_must_have_local_version_reach_main_and_have_authored_notes():
    text = _text()
    assert "canonical_tag_re='^v" in text
    assert '[[ ! "$TAG_NAME" =~ $canonical_tag_re ]]' in text
    assert "without leading-zero numeric atoms" in text
    assert text.count("git/ref/tags/$TAG_NAME") == 2
    assert text.count("git/tags/$tag_object_sha") == 2
    assert '[[ "$object_type" != "tag"' in text
    assert '[[ "$target_type" != "commit"' in text
    assert '[[ "$source_sha" != "$GITHUB_SHA" ]]' in text
    assert text.count("compare/$source_sha...main") == 2
    assert '"ahead" && "$main_relation" != "identical"' in text
    assert 'echo "source_sha=$source_sha"' in text
    assert 'echo "tag_object_sha=$tag_object_sha"' in text
    assert 'notes_path="docs/releases/$TAG_NAME.md"' in text
    assert '! -f "$notes_path" || -L "$notes_path" || ! -s "$notes_path"' in text
    assert 'expected_heading="# Yoke ${TAG_NAME#v}"' in text
    assert '[[ "$heading" != "$expected_heading" ]]' in text


def test_release_reuses_attested_wheel_factory_with_only_signing_scope():
    text = _text()
    assert "uses: ./.github/workflows/yoke-build-artifacts.yml" in text
    build_start = text.index("  build:\n")
    release_start = text.index("  release:\n")
    build_block = text[build_start:release_start]
    assert "needs: validate-tag" in build_block
    assert "contents: read" in build_block
    assert "attestations: write" in build_block
    assert "id-token: write" in build_block
    assert "actions: read" in build_block
    assert "contents: write" not in build_block
    assert "secrets: inherit" not in build_block


def test_built_version_and_transferred_wheels_are_reverified():
    text = _text()
    assert "name: ${{ needs.build.outputs.artifact_name }}" in text
    assert '[[ "$TAG_NAME" != "v$RELEASE_VERSION" ]]' in text
    assert 'records_path = root / "release-records.json"' in text
    assert "python3 -I - <<'PY'" in text
    assert 'actual = {path.name for path in wheels_dir.glob("*.whl")}' in text
    assert "if actual != expected:" in text
    assert "hashlib.sha256(body).hexdigest()" in text
    assert 'int(record["size"])' in text
    assert 'gh attestation verify "$wheel"' in text
    assert (
        '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/yoke-build-artifacts.yml"'
        in text
    )
    assert '--source-ref "$GITHUB_REF"' in text
    assert '--source-digest "$GITHUB_SHA"' in text
    assert "--deny-self-hosted-runners" in text


def test_release_creation_uses_tag_notes_and_validated_assets():
    text = _text()
    verify_index = text.index("Verify tag, manifest, and transferred wheel bytes")
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
    assert '--notes-file "docs/releases/$TAG_NAME.md"' in text


def test_public_operator_doc_starts_future_only_and_teaches_verification():
    text = _DOC.read_text(encoding="utf-8")
    assert "deliberately not backfilled" in text
    assert "docs/releases/vX.Y.Z+local.N.md" in text
    assert "Treat release tags as immutable" in text
    assert "gh attestation verify ./yoke_core-*.whl" in text
    assert "oci://ghcr.io/upyoke/yoke-server@sha256:<digest>" in text
    assert '--source-ref "$release_ref"' in text
    assert '--source-ref "refs/tags/$tag"' in text
    assert '--source-ref "refs/tags/$image_tag"' in text
    assert text.count("--source-digest") == 3
    assert "--deny-self-hosted-runners" in text
    contributing = (_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "[docs/releases/README.md](docs/releases/README.md)" in contributing
