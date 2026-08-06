"""Verifier doubles for migration adoption tests."""

from __future__ import annotations

from yoke_core.domain.migration_artifact_trust import (
    MIGRATION_MANIFEST_ROLE,
    SOURCE_ARTIFACT_ROLE,
    ArtifactVerificationReceipt,
    ArtifactVerificationSubject,
    ArtifactVerifier,
)
from yoke_core.domain.migration_history_manifest import MigrationHistoryManifest


TEST_SOURCE_REPOSITORY = "example/project"
TEST_SIGNER_IDENTITY = "example/project/.github/workflows/build-artifacts.yml"


def artifact_verifier_for(
    manifest: MigrationHistoryManifest,
    *,
    source_commit: str | None = None,
    source_sha256: str | None = None,
    manifest_sha256: str | None = None,
) -> ArtifactVerifier:
    """Return a project verifier double bound to one manifest."""
    receipt = ArtifactVerificationReceipt(
        verifier="test-attestation-verifier/v1",
        source_repository=TEST_SOURCE_REPOSITORY,
        source_commit=source_commit or manifest.artifact.source_commit,
        signer_identity=TEST_SIGNER_IDENTITY,
        subjects=(
            ArtifactVerificationSubject(
                role=SOURCE_ARTIFACT_ROLE,
                name=manifest.artifact.source_artifact,
                sha256=source_sha256 or manifest.artifact.source_sha256,
            ),
            ArtifactVerificationSubject(
                role=MIGRATION_MANIFEST_ROLE,
                name="migration-history.json",
                sha256=manifest_sha256 or manifest.content_sha256,
            ),
        ),
    )
    return lambda _request: receipt


__all__ = [
    "TEST_SIGNER_IDENTITY",
    "TEST_SOURCE_REPOSITORY",
    "artifact_verifier_for",
]
