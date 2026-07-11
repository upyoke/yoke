"""Supply-chain contract for the public wheel factory workflow.

The factory remains useful on untrusted fork pull requests, but only trusted
push/dispatch callers may receive the OIDC identity and repository write scope
needed to sign provenance. The attested subjects must be the exact product
wheels that passed ``validate-release`` — not the checksum manifest or the
larger release directory — and attestation must precede artifact upload.
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
    assert re.findall(r"^\s+runs-on:\s*(.+)$", text, re.MULTILINE) == ["ubuntu-latest"]
    assert "runs-on: ${{ vars.YOKE_LINUX_RUNS_ON }}" not in text
    assert not re.findall(r"secrets\.([A-Za-z_0-9]+)", text)
    for needle in ("aws-actions", "YOKE_CI_ROLE_ARN", "AWS_REGION"):
        assert needle not in text, f"operator surface leaked in: {needle}"


def test_attestation_permissions_are_narrow():
    text = _text()
    assert "contents: read" in text
    assert "attestations: write" in text
    assert "id-token: write" in text
    assert "contents: write" not in text
    assert "packages: write" not in text
    assert "artifact-metadata" not in text


def test_only_trusted_callers_attest():
    text = _text()
    assert (
        "if: github.event_name == 'push' || "
        "github.event_name == 'workflow_dispatch'" in text
    )
    assert "uses: actions/attest@v4" in text


def test_attests_exact_validated_wheels_before_upload():
    text = _text()
    validate_index = text.index('validate-release "$release_dir"')
    attest_index = text.index("uses: actions/attest@v4")
    upload_index = text.index("uses: actions/upload-artifact@v4")
    assert validate_index < attest_index < upload_index
    assert 'echo "wheels_glob=$release_dir/wheels/*.whl"' in text
    assert "subject-path: ${{ steps.release.outputs.wheels_glob }}" in text
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
