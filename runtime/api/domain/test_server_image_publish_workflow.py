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


def test_publish_gate_requires_repository_variable_and_main_ref():
    text = _text()
    assert "vars.YOKE_PUBLISH_SERVER_IMAGE == 'true'" in text
    assert "github.ref == 'refs/heads/main'" in text


def test_publication_is_globally_serialized():
    text = _text()
    assert "group: yoke-server-image-publication" in text
    assert "group: ${{ github.workflow }}-${{ github.ref }}" not in text
    assert "cancel-in-progress: false" in text


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


def test_one_build_pushes_by_digest_before_publishing_main_tags():
    text = _text()
    assert "fetch-depth: 0" in text
    assert "persist-credentials: false" in text
    assert "setuptools-scm[toml]==10.2.0" in text
    assert "python -m setuptools_scm --root" in text
    assert text.count("uses: docker/build-push-action@") == 1
    assert "push: true" in text
    assert "push-by-digest=true" in text
    assert "name-canonical=true" in text
    assert "YOKE_BUILD_SHA=${{ steps.image.outputs.sha_tag }}" in text
    assert "YOKE_ENGINE_VERSION=${{ steps.version.outputs.value }}" in text
    assert "ghcr.io/${owner,,}/yoke-server" in text
    assert 'sha_tag="${GITHUB_SHA:0:12}"' in text
    assert 'echo "sha_ref=$repository:$sha_tag"' in text
    assert 'echo "latest_ref=$repository:latest"' in text


def test_conflicting_sha12_is_refused_and_both_tags_are_verified():
    text = _text()
    build_index = text.index("uses: docker/build-push-action@")
    conflict_index = text.index("refusing conflicting immutable sha12")
    latest_index = text.index('--tag "$LATEST_REF"')
    verify_index = text.index("Verify published references resolve to the built digest")
    attest_index = text.index("uses: actions/attest@")
    assert build_index < conflict_index < latest_index < verify_index < attest_index
    assert '"$existing_digest" != "$PUSHED_DIGEST"' in text
    assert text.count("--prefer-index=false") == 2
    assert '--tag "$SHA_REF" "$REPOSITORY@$PUSHED_DIGEST"' in text
    assert '--tag "$LATEST_REF" "$REPOSITORY@$PUSHED_DIGEST"' in text
    assert '"$sha_digest" != "$PUSHED_DIGEST"' in text
    assert '"$latest_digest" != "$PUSHED_DIGEST"' in text


def test_attestation_binds_build_output_digest_and_registry_subject():
    text = _text()
    build_index = text.index("uses: docker/build-push-action@")
    attest_index = text.index("uses: actions/attest@")
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
