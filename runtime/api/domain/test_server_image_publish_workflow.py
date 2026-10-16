"""Fail-closed provenance contract for the public GHCR image factory.

Main builds exact content. Immutable annotated release tags only promote it.
Native architecture jobs push content digests, a separate job assembles the
multi-platform manifest under an internal staging reference, a no-checkout job
attests it, and only then may a separate job publish the release references.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from yoke_core.tools import server_image_metadata


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "yoke-server-image.yml"
_RELEASE_DOC = _ROOT / "docs" / "releases" / "README.md"


def _text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_main_push_builds_and_canonical_tags_promote():
    text = _text()
    trigger = text[text.index("on:\n") : text.index("\nconcurrency:")]
    assert "push:" in trigger
    assert 'tags: ["[0-9]*"]' in trigger
    assert "branches: [main]" in trigger
    assert "pull_request" not in trigger
    assert "workflow_dispatch" not in trigger


def test_release_tags_build_concurrently_without_latest_rollback():
    text = _text()
    build = text.split("  build:\n", 1)[1].split("\n  assemble:\n", 1)[0]
    assemble = text.split("  assemble:\n", 1)[1].split("\n  attest:\n", 1)[0]
    assert "needs: validate-tag" in build
    assert "packages: write" in build
    assert "needs: [validate-tag, build]" in assemble
    assert "group: ${{ github.workflow }}-${{ github.sha }}-${{ github.ref }}" in text
    assert "cancel-in-progress: false" in text
    assert "group: yoke-server-image-publication-${{ github.repository }}" in text
    assert "publish_server_image.py" in text


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
    attest = text[attest_start : text.index("  record:\n")]
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
    assert "uses: actions/checkout@" in publish
    assert "attestations: read" in publish
    assert "uses: docker/build-push-action@" not in publish
    assert "artifact-metadata" not in text


def test_every_job_is_github_hosted_and_operator_credentials_are_absent():
    text = _text()
    assert re.findall(r"^\s+runs-on:\s*(.+)$", text, re.MULTILINE) == [
        "ubuntu-latest",
        "${{ matrix.runner }}",
        "${{ matrix.runner }}",
        "ubuntu-latest",
        "ubuntu-latest",
        "ubuntu-latest",
        "ubuntu-latest",
    ]
    assert "vars.YOKE_LINUX_RUNS_ON" not in text
    assert "runs-on: self-hosted" not in text
    secret_refs = set(re.findall(r"secrets\.([A-Za-z_0-9]+)", text))
    assert secret_refs <= {"GITHUB_TOKEN"}
    for needle in ("ECR", "aws-actions", "YOKE_CI_ROLE_ARN", "AWS_REGION"):
        assert needle not in text, f"operator surface leaked in: {needle}"


def test_remote_tag_is_validated_and_publication_revalidates_its_object():
    text = _text()
    assert "release_tag_validation.py" in text
    assert "publish_server_image.py" in text
    assert (
        "EXPECTED_TAG_OBJECT_SHA: ${{ needs.validate-tag.outputs.tag_object_sha }}"
        in text
    )
    helper = (
        _ROOT / "packages/yoke-core/src/yoke_core/tools/publish_server_image.py"
    ).read_text()
    assert "identity = validate_release_tag(env)" in helper
    assert 'identity["tag_object_sha"] != env["EXPECTED_TAG_OBJECT_SHA"]' in helper


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
    assert "python -m setuptools_scm" not in build
    assert 'pip install "setuptools-scm' not in build
    assert build.count("uses: docker/build-push-action@") == 1
    assert "push-by-digest=true" in build
    assert "name-canonical=true" in build
    assert "provenance: false" in build
    assert "tags:" not in build
    assert "YOKE_BUILD_SHA=${{ needs.validate-tag.outputs.source_sha }}" in build
    assert "EXPECTED_BUILD: ${{ needs.validate-tag.outputs.source_sha }}" in build
    assert (
        "YOKE_ENGINE_VERSION=${{ needs.validate-tag.outputs.release_version }}" in build
    )
    assert "if: github.ref == 'refs/heads/main'" in build
    assert "Verify native architecture and installed release metadata" in build
    assert "server_image_metadata.py verify-native" in build
    assert '--image-ref "$REPOSITORY@$PUSHED_DIGEST"' in build
    assert '--expected-arch "$EXPECTED_ARCH"' in build
    assert '--digest-dir "$RUNNER_TEMP/digests"' in build
    assert "sed -n '1p'" not in build
    assert "sed -n '2p'" not in build
    assert "uses: actions/upload-artifact@" in build


def test_queue_checks_both_architectures_without_registry_or_signing_authority():
    text = _text()
    check = text.split("  check-build:\n", 1)[1].split("  build:\n", 1)[0]
    assert "if: github.event_name == 'merge_group'" in check
    assert "permissions: {contents: read}" in check
    assert "push: false" in check
    assert "linux/amd64" in check and "linux/arm64" in check
    assert "ubuntu-latest" in check and "ubuntu-24.04-arm" in check
    assert "persist-credentials: false" in check
    for forbidden in ("packages: write", "id-token", "attestations:", "login-action"):
        assert forbidden not in check


def test_metadata_parser_ignores_output_before_the_marked_envelope():
    expected = server_image_metadata.ServerImageMetadata(
        version="0.1.1+launch.231",
        build="98f040f7afbb",
    )
    output = "incidental output\n" + server_image_metadata.format_metadata_line(
        expected
    )

    assert server_image_metadata.parse_metadata_output(output) == expected


def test_metadata_entrypoint_keeps_stdout_machine_parseable():
    env = dict(os.environ)
    env["YOKE_BUILD_SHA"] = "image-build-test"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.tools.server_image_metadata",
            "emit",
        ],
        cwd=_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    parsed = server_image_metadata.parse_metadata_output(completed.stdout)
    assert parsed.build == "image-build-test"
    assert completed.stdout == server_image_metadata.format_metadata_line(parsed) + "\n"
    assert "ObservabilityConfigured" not in completed.stdout


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


def test_record_requires_attestation_and_publication_verifies_the_main_digest():
    text = _text()
    record = text.split("  record:\n", 1)[1].split("  publish-tags:\n", 1)[0]
    publish = text.split("  publish-tags:\n", 1)[1]
    assert "needs: [validate-tag, assemble, attest]" in record
    assert "name: yoke-image-${{ github.sha }}" in record
    assert "promote_main_artifacts.py image" in publish
    assert publish.index("promote_main_artifacts.py image") < publish.index(
        "publish_server_image.py"
    )
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


def test_digest_publication_has_collision_platform_and_reference_verification():
    helper = (
        _ROOT / "packages/yoke-core/src/yoke_core/tools/publish_server_image.py"
    ).read_text()
    assert "existing is not None and existing != digest" in helper
    assert "release_image_collision" in helper
    assert "--prefer-index=false" in helper
    assert "if inspect(reference) != digest" in helper
    assert 'platforms != {"linux/amd64", "linux/arm64"}' in helper
    assert helper.index("platforms !=") < helper.index("references = [immutable]")


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
    assert "--source-ref refs/heads/main" in text
    assert '--source-digest "$source_sha"' in text
    for receipt_field in (
        "workflow-run URL",
        "annotated tag-object SHA",
        "peeled source SHA",
        "image digest",
        "both anonymous platform pulls",
    ):
        assert receipt_field in text
