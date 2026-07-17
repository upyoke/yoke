"""Fail-closed provenance contract for the public GHCR image factory.

Only an immutable annotated release tag reachable from current main may build.
Native architecture jobs push content digests, a separate job assembles the
multi-platform manifest under an internal staging reference, a no-checkout job
attests it, and only then may a separate job publish the release references.
"""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "yoke-server-image.yml"
_RELEASE_DOC = _ROOT / "docs" / "releases" / "README.md"


def _text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_only_release_tag_pushes_trigger_the_factory():
    text = _text()
    trigger = text[text.index("on:\n") : text.index("\nconcurrency:")]
    assert "push:" in trigger
    assert '      - "v*"' in trigger
    assert "branches:" not in trigger
    assert "pull_request" not in trigger
    assert "workflow_dispatch" not in trigger


def test_every_validated_release_builds_in_one_serial_publication_lane():
    text = _text()
    build = text.split("  build:\n", 1)[1].split("\n  assemble:\n", 1)[0]
    assemble = text.split("  assemble:\n", 1)[1].split("\n  attest:\n", 1)[0]
    assert "needs: validate-tag" in build
    assert "packages: write" in build
    assert "needs: [validate-tag, build]" in assemble
    assert "group: yoke-server-image-publication" in text
    assert "cancel-in-progress: false" in text


def test_permissions_are_split_by_validation_build_signing_and_publication():
    text = _text()
    validate_start = text.index("  validate-tag:\n")
    build_start = text.index("  build:\n")
    assemble_start = text.index("  assemble:\n")
    attest_start = text.index("  attest:\n")
    publish_start = text.index("  publish-tags:\n")
    validate = text[validate_start:build_start]
    build = text[build_start:assemble_start]
    assemble = text[assemble_start:attest_start]
    attest = text[attest_start:publish_start]
    publish = text[publish_start:]

    assert "permissions: {}" in text[:validate_start]
    assert "contents: read" in validate
    assert "packages: write" not in validate
    assert "attestations: write" not in validate
    assert "id-token: write" not in validate

    assert "contents: read" in build
    assert "packages: write" in build
    assert "attestations: write" not in build
    assert "id-token: write" not in build

    assert "actions: read" in assemble
    assert "packages: write" in assemble
    assert "contents: read" not in assemble
    assert "attestations: write" not in assemble
    assert "id-token: write" not in assemble

    for permission in (
        "attestations: write",
        "contents: read",
        "id-token: write",
        "packages: write",
    ):
        assert permission in attest
    assert "uses: docker/login-action@" in attest
    assert "uses: actions/checkout@" not in attest
    assert not re.findall(r"^\s+run:\s*", attest, re.MULTILINE)

    assert "contents: read" in publish
    assert "packages: write" in publish
    assert "attestations: write" not in publish
    assert "id-token: write" not in publish
    assert "uses: actions/checkout@" not in publish
    assert "artifact-metadata" not in text


def test_every_job_is_github_hosted_and_operator_credentials_are_absent():
    text = _text()
    assert re.findall(r"^\s+runs-on:\s*(.+)$", text, re.MULTILINE) == [
        "ubuntu-latest",
        "${{ matrix.runner }}",
        "ubuntu-latest",
        "ubuntu-latest",
        "ubuntu-latest",
    ]
    assert "YOKE_LINUX_RUNS_ON" not in text
    assert "runs-on: self-hosted" not in text
    secret_refs = set(re.findall(r"secrets\.([A-Za-z_0-9]+)", text))
    assert secret_refs <= {"GITHUB_TOKEN"}
    for needle in ("ECR", "aws-actions", "YOKE_CI_ROLE_ARN", "AWS_REGION"):
        assert needle not in text, f"operator surface leaked in: {needle}"


def test_remote_annotated_tag_and_current_main_are_checked_twice():
    text = _text()
    assert "canonical_tag_re='^v" in text
    assert '"$TAG_NAME" =~ $canonical_tag_re' in text
    assert "without leading-zero numeric atoms" in text
    assert text.count("git/ref/tags/$TAG_NAME") == 2
    assert text.count("git/tags/$tag_object_sha") == 2
    assert text.count('[[ "$object_type" != "tag"') == 2
    assert text.count('[[ "$target_type" != "commit"') == 2
    assert text.count("compare/$source_sha...main") == 2
    assert '"$source_sha" != "$GITHUB_SHA"' in text
    assert "EXPECTED_SOURCE_SHA: ${{ needs.validate-tag.outputs.source_sha }}" in text
    assert (
        "EXPECTED_TAG_OBJECT_SHA: "
        "${{ needs.validate-tag.outputs.tag_object_sha }}" in text
    )


def test_build_uses_native_runners_and_pushes_only_by_digest():
    text = _text()
    build_start = text.index("  build:\n")
    assemble_start = text.index("  assemble:\n")
    build = text[build_start:assemble_start]
    assert "fetch-depth: 0" in build
    assert "persist-credentials: false" in build
    assert "ref: ${{ needs.validate-tag.outputs.source_sha }}" in build
    assert "uses: docker/setup-qemu-action@" not in text
    assert "uses: docker/setup-buildx-action@" in build
    assert "runner: ubuntu-latest" in build
    assert "runner: ubuntu-24.04-arm" in build
    assert "platform: linux/amd64" in build
    assert "platform: linux/arm64" in build
    assert "platforms: ${{ matrix.platform }}" in build
    assert 'echo "release_version=${TAG_NAME#v}"' in text
    assert "python -m setuptools_scm" not in build
    assert 'pip install "setuptools-scm' not in build
    assert text.count("uses: docker/build-push-action@") == 1
    assert "push-by-digest=true" in build
    assert "name-canonical=true" in build
    assert "provenance: false" in build
    assert "tags:" not in build
    assert "YOKE_BUILD_SHA=${{ needs.validate-tag.outputs.sha_tag }}" in build
    assert (
        "YOKE_ENGINE_VERSION=${{ needs.validate-tag.outputs.release_version }}" in build
    )
    assert 'source_sha="$(jq -r' in text
    assert 'sha_tag="${source_sha:0:12}"' in text
    assert 'echo "sha_ref=$repository:$sha_tag"' in text
    assert 'echo "latest_ref=$repository:latest"' in text
    assert "Verify native architecture and installed release metadata" in build
    assert 'image_ref="$REPOSITORY@$PUSHED_DIGEST"' in build
    assert "docker image inspect" in build
    assert '"$actual_arch" != "$EXPECTED_ARCH"' in build
    assert 'version("yoke-core")' in build
    assert '"$actual_version" != "$EXPECTED_VERSION"' in build
    assert '"$actual_build" != "$EXPECTED_BUILD"' in build
    assert "uses: actions/upload-artifact@" in build


def test_native_digests_are_assembled_and_verified_before_attestation():
    text = _text()
    assemble = text.split("  assemble:\n", 1)[1].split("\n  attest:\n", 1)[0]
    assert "uses: actions/download-artifact@" in assemble
    assert "merge-multiple: true" in assemble
    assert '"${#digest_files[@]}" -ne 2' in assemble
    assert '--tag "$staging_ref"' in assemble
    assert "--metadata-file" in assemble
    assert '."containerimage.descriptor".digest' in assemble
    assert '"$registry_digest" != "$digest"' in assemble
    assert '"$platforms" != "linux/amd64,linux/arm64"' in assemble


def test_digest_is_attested_before_any_named_reference_is_published():
    text = _text()
    build_index = text.index("uses: docker/build-push-action@")
    assemble_index = text.index('--tag "$staging_ref"')
    attest_index = text.index("uses: actions/attest@")
    sha_tag_index = text.index('--tag "$SHA_REF"')
    latest_tag_index = text.index('--tag "$LATEST_REF"')
    verify_index = text.index("Verify published references resolve to the built digest")
    assert (
        build_index < assemble_index < attest_index
        < sha_tag_index < latest_tag_index < verify_index
    )
    assert "needs: [validate-tag, assemble, attest]" in text
    assert "subject-name: ${{ needs.validate-tag.outputs.repository }}" in text
    assert "subject-digest: ${{ needs.assemble.outputs.digest }}" in text
    assert "push-to-registry: true" in text
    assert "create-storage-record: false" in text


def test_digest_attestation_retries_transport_failures_before_publication():
    text = _text()
    attest = text.split("  attest:\n", 1)[1].split("\n  publish-tags:\n", 1)[0]
    assert attest.count("uses: actions/attest@") == 3
    assert "id: attest_attempt_1" in attest
    assert "id: attest_attempt_2" in attest
    assert attest.count("continue-on-error: true") == 2
    assert "steps.attest_attempt_1.outcome != 'success'" in attest
    assert "steps.attest_attempt_2.outcome != 'success'" in attest
    assert attest.count("subject-digest: ${{ needs.assemble.outputs.digest }}") == 3
    assert attest.count("push-to-registry: true") == 3


def test_conflicting_sha12_is_refused_and_both_tags_are_verified():
    text = _text()
    assert '"$existing_digest" != "$PUSHED_DIGEST"' in text
    assert "refusing conflicting immutable sha12" in text
    assert text.count("--prefer-index=false") == 2
    assert '--tag "$SHA_REF" "$REPOSITORY@$PUSHED_DIGEST"' in text
    assert '--tag "$LATEST_REF" "$REPOSITORY@$PUSHED_DIGEST"' in text
    assert '"$sha_digest" != "$PUSHED_DIGEST"' in text
    assert '"$latest_digest" != "$PUSHED_DIGEST"' in text
    assert '"$platforms" != "linux/amd64,linux/arm64"' in text


def test_registry_logins_use_the_pinned_action():
    text = _text()
    assert text.count("uses: docker/login-action@") == 4
    assert "docker login ghcr.io" not in text


def test_first_publication_contract_proves_visibility_pull_and_provenance():
    text = _RELEASE_DOC.read_text(encoding="utf-8")
    assert "## First public image publication" in text
    assert "visibility to **Public**" in text
    assert "Repository visibility alone is not sufficient" in text
    assert 'anonymous_config="$(mktemp -d)"' in text
    assert "docker pull --platform linux/amd64" in text
    assert "docker pull --platform linux/arm64" in text
    assert 'DOCKER_CONFIG="$anonymous_config" docker pull "$repository:latest"' in text
    assert 'test "$sha_digest" = "$digest"' in text
    assert 'test "$latest_digest" = "$digest"' in text
    assert 'test "$platforms" = "linux/amd64,linux/arm64"' in text
    assert 'DOCKER_CONFIG="$anonymous_config" gh attestation verify' in text
    assert "--bundle-from-oci" in text
    assert '--source-ref "refs/tags/$tag"' in text
    assert '--source-digest "$source_sha"' in text
    for receipt_field in (
        "workflow-run URL",
        "annotated tag-object SHA",
        "peeled source SHA",
        "image digest",
        "both anonymous platform pulls",
    ):
        assert receipt_field in text
