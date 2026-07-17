"""Supply-chain contract for the public wheel factory workflow.

Untrusted repository code builds with read-only contents permission. Only a
separate no-checkout, no-shell job on a trusted ref receives signing authority,
and it signs the exact validated wheels transferred through the artifact
service.
"""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = "yoke-build-artifacts.yml"


def _text() -> str:
    workflows_dir = _ROOT / ".github" / "workflows"
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
    assert 'python -m pip install "uv==0.11.28"' in build_block


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


def test_signer_retries_transient_attestation_transport_failures():
    signer = _text().split("  attest:\n", 1)[1]
    assert signer.count("uses: actions/attest@") == 3
    assert "id: attest_attempt_1" in signer
    assert "id: attest_attempt_2" in signer
    assert signer.count("continue-on-error: true") == 2
    assert "steps.attest_attempt_1.outcome != 'success'" in signer
    assert "steps.attest_attempt_2.outcome != 'success'" in signer
    assert signer.count(
        "subject-path: ${{ runner.temp }}/validated-release/wheels/*.whl"
    ) == 3


def test_validated_identity_drives_reusable_outputs_and_upload_name():
    text = _text()
    assert 'json.load(open(sys.argv[1], encoding="utf-8"))["version"]' in text
    assert "release_version: ${{ steps.release.outputs.release_version }}" in text
    assert 'echo "artifact_name=yoke-release-${GITHUB_SHA}"' in text
    assert "artifact_name: ${{ steps.release.outputs.artifact_name }}" in text
    assert "name: ${{ steps.release.outputs.artifact_name }}" in text
    assert "overwrite: true" in text


def test_factory_uv_pin_matches_project_dependencies_and_lock():
    workflow = _text()
    project = _ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8")
    lock = _ROOT.joinpath("uv.lock").read_text(encoding="utf-8")
    assert 'python -m pip install "uv==0.11.28"' in workflow
    assert project.count('"uv==0.11.28"') == 2
    assert 'name = "uv"\nversion = "0.11.28"' in lock
    assert 'specifier = "==0.11.28"' in lock
    assert set(re.findall(r"uv==([0-9.]+)", workflow + project)) == {"0.11.28"}


def test_all_product_build_backends_are_exactly_pinned():
    pyprojects = [_ROOT / "pyproject.toml"]
    pyprojects.extend(sorted((_ROOT / "packages").glob("yoke-*/pyproject.toml")))
    expected = {
        "setuptools==82.0.1; python_version < '3.10'",
        "setuptools==83.0.0; python_version >= '3.10'",
        "setuptools-scm[toml]==10.2.0",
    }
    for path in pyprojects:
        text = path.read_text(encoding="utf-8")
        build_system = text.split("[project]", 1)[0]
        requirements = set(re.findall(r'^\s*"([^"]+)",?$', build_system, re.MULTILINE))
        assert requirements == expected, f"floating or stale PEP 517 backend: {path}"
