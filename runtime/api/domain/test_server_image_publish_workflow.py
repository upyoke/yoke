"""Fork-safety contract for the GHCR server-image publish workflow.

The workflow is a FACTORY lane: it must stay reachable only from trusted
refs (push to main, manual dispatch), stay dormant until the publish
repository variable is flipped, run only on GitHub-hosted runners, and
touch no operator secret or registry. The sha12 and latest names must come
from one image build, and the authenticated provenance statement must bind
that build's exact registry digest. A regression on any of these properties
would either expose publishing authority or leave consumers unable to prove
which source and workflow produced the bytes they pulled.
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = "yoke-server-image.yml"


def _text() -> str:
    workflows_dir = Path(__file__).resolve().parents[3] / ".github" / "workflows"
    return workflows_dir.joinpath(_WORKFLOW).read_text(encoding="utf-8")


def test_never_triggered_by_pull_request():
    text = _text()
    assert "pull_request" not in text
    assert "\n  push:\n    branches: [main]" in text
    assert "workflow_dispatch:" in text


def test_publish_gate_is_repository_variable():
    assert "vars.YOKE_PUBLISH_SERVER_IMAGE == 'true'" in _text()


def test_permissions_are_minimal():
    text = _text()
    assert "contents: read" in text
    assert "packages: write" in text
    assert "attestations: write" in text
    assert "id-token: write" in text
    # The attestation action is explicitly kept off the broader organization
    # artifact-metadata surface; no cloud-role assumption exists in this lane.
    assert "artifact-metadata" not in text


def test_hosted_runner_hard_pin():
    text = _text()
    assert "runs-on: ubuntu-latest" in text
    assert "YOKE_LINUX_RUNS_ON" not in text
    assert "self-hosted" not in text


def test_no_operator_secrets_or_registry():
    text = _text()
    secret_refs = set(re.findall(r"secrets\.([A-Za-z_0-9]+)", text))
    assert secret_refs <= {"GITHUB_TOKEN"}, (
        f"unexpected secret references: {sorted(secret_refs)}"
    )
    for needle in ("ECR", "aws-actions", "YOKE_CI_ROLE_ARN", "AWS_REGION"):
        assert needle not in text, f"operator surface leaked in: {needle}"


def test_one_build_pushes_sha12_and_main_only_latest_tags():
    text = _text()
    assert "fetch-depth: 0" in text
    assert "python -m setuptools_scm --root" in text
    assert "uses: docker/build-push-action@v6" in text
    assert text.count("uses: docker/build-push-action@v6") == 1
    assert "push: true" in text
    assert "YOKE_BUILD_SHA=${{ steps.image.outputs.sha_tag }}" in text
    assert "YOKE_ENGINE_VERSION=${{ steps.version.outputs.value }}" in text
    assert "ghcr.io/${owner,,}/yoke-server" in text
    assert 'sha_tag="${GITHUB_SHA:0:12}"' in text
    assert 'echo "$repository:$sha_tag"' in text
    # latest only advances from main; dispatch on another ref publishes
    # the sha tag alone.
    assert 'if [[ "$GITHUB_REF" == "refs/heads/main" ]]' in text
    assert 'echo "$repository:latest"' in text


def test_attestation_binds_build_output_digest_and_registry_subject():
    text = _text()
    build_index = text.index("uses: docker/build-push-action@v6")
    attest_index = text.index("uses: actions/attest@v4")
    assert build_index < attest_index
    assert "id: push" in text[:build_index]
    assert "subject-name: ${{ steps.image.outputs.repository }}" in text
    assert "subject-digest: ${{ steps.push.outputs.digest }}" in text
    assert "push-to-registry: true" in text
    assert "create-storage-record: false" in text


def test_login_pipe_preserves_failure_status():
    text = _text()
    assert "set -o pipefail" in text
    assert "| docker login ghcr.io" in text
