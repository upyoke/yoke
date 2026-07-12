"""Supply-chain contract for the public wheel factory workflow.

Untrusted repository code builds with read-only contents permission. Only a
separate no-checkout, no-shell job on a trusted ref receives signing authority,
and it signs the exact validated wheels transferred through the artifact
service.
"""

from __future__ import annotations

import re
from pathlib import Path


_WORKFLOW = "yoke-build-artifacts.yml"


def _text() -> str:
    workflows_dir = Path(__file__).resolve().parents[3] / ".github" / "workflows"
    return workflows_dir.joinpath(_WORKFLOW).read_text(encoding="utf-8")


def test_remains_fork_buildable_and_reusable_by_release_factory():
    text = _text()
    assert "\n  pull_request:\n    branches: [main]" in text
    assert "\n  push:\n    branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert "workflow_call:" in text
    assert "value: ${{ jobs.build.outputs.release_version }}" in text
    assert "value: ${{ jobs.build.outputs.artifact_name }}" in text
    assert "group: yoke-build-artifacts-${{ github.ref }}" in text
    assert "group: ${{ github.workflow }}-${{ github.ref }}" not in text


def test_hosted_runner_and_no_operator_credentials():
    text = _text()
    assert re.findall(r"^\s+runs-on:\s*(.+)$", text, re.MULTILINE) == [
        "ubuntu-latest",
        "ubuntu-latest",
    ]
    assert "runs-on: ${{ vars.YOKE_LINUX_RUNS_ON }}" not in text
    assert not re.findall(r"secrets\.([A-Za-z_0-9]+)", text)
    for needle in ("aws-actions", "YOKE_CI_ROLE_ARN", "AWS_REGION"):
        assert needle not in text, f"operator surface leaked in: {needle}"


def test_untrusted_build_has_no_signing_authority():
    text = _text()
    assert "permissions: {}" in text
    build_start = text.index("  build:\n")
    signer_start = text.index("  attest:\n")
    build_block = text[build_start:signer_start]
    assert "permissions:\n      contents: read" in build_block
    assert "attestations: write" not in build_block
    assert "id-token: write" not in build_block
    assert "actions: write" not in build_block
    assert "contents: write" not in text
    assert "packages: write" not in text
    assert "artifact-metadata" not in text
    assert "persist-credentials: false" in build_block
    assert 'python -m pip install "uv==0.11.21"' in build_block


def test_only_trusted_ref_signer_attests_without_repository_code():
    text = _text()
    signer = text[text.index("  attest:\n") :]
    assert "needs: build" in signer
    assert "github.ref == 'refs/heads/main'" in signer
    assert "startsWith(github.ref, 'refs/tags/v')" in signer
    assert "actions: read" in signer
    assert "attestations: write" in signer
    assert "contents: read" in signer
    assert "id-token: write" in signer
    assert "uses: actions/download-artifact@" in signer
    assert "uses: actions/attest@" in signer
    assert "uses: actions/checkout@" not in signer
    assert not re.findall(r"^\s+run:\s*", signer, re.MULTILINE)


def test_signer_attests_exact_validated_wheels_after_transfer():
    text = _text()
    validate_index = text.index('validate-release "$release_dir"')
    upload_index = text.index("uses: actions/upload-artifact@")
    download_index = text.index("uses: actions/download-artifact@")
    attest_index = text.index("uses: actions/attest@")
    assert validate_index < upload_index < download_index < attest_index
    assert "subject-path: ${{ runner.temp }}/validated-release/wheels/*.whl" in text
    assert "subject-checksums:" not in text
    assert "subject-path: ${{ env.RELEASE_DIR }}" not in text


def test_validated_identity_drives_reusable_outputs_and_upload_name():
    text = _text()
    assert 'json.load(open(sys.argv[1], encoding="utf-8"))["version"]' in text
    assert "release_version: ${{ steps.release.outputs.release_version }}" in text
    assert 'echo "artifact_name=yoke-release-${GITHUB_SHA}"' in text
    assert "artifact_name: ${{ steps.release.outputs.artifact_name }}" in text
    assert "name: ${{ steps.release.outputs.artifact_name }}" in text
    assert "overwrite: true" in text
