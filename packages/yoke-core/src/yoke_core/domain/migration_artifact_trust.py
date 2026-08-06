"""Project-neutral trust contract for migration adoption artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, Tuple

from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_history_manifest import (
    MIGRATION_HISTORY_MANIFEST_FILENAME,
    SOURCE_COMMIT_PATTERN,
    ArtifactIdentity,
    MigrationHistoryManifest,
)


SOURCE_ARTIFACT_ROLE = "source_artifact"
MIGRATION_MANIFEST_ROLE = "migration_manifest"
VERIFICATION_RECEIPT_SCHEMA_VERSION = 1
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ArtifactVerificationError(ValueError):
    """A project verifier is absent or did not bind the selected artifacts."""


@dataclass(frozen=True)
class ArtifactVerificationSubject:
    """One verifier-authenticated subject included in a safe receipt."""

    role: str
    name: str
    sha256: str

    def __post_init__(self) -> None:
        if _ROLE_PATTERN.fullmatch(self.role) is None:
            raise ArtifactVerificationError(
                "artifact verification subject role is not canonical"
            )
        if not self.name.strip():
            raise ArtifactVerificationError(
                "artifact verification subject name is empty"
            )
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ArtifactVerificationError(
                "artifact verification subject SHA256 is invalid"
            )


@dataclass(frozen=True)
class ArtifactVerificationRequest:
    """Artifact identities a project verifier must authenticate."""

    artifact: ArtifactIdentity
    manifest_sha256: str
    manifest_name: str = MIGRATION_HISTORY_MANIFEST_FILENAME

    def __post_init__(self) -> None:
        if not SHA256_PATTERN.fullmatch(self.manifest_sha256):
            raise ArtifactVerificationError(
                "artifact verification manifest SHA256 is invalid"
            )
        if not self.manifest_name.strip():
            raise ArtifactVerificationError(
                "artifact verification manifest name is empty"
            )


@dataclass(frozen=True)
class ArtifactVerificationReceipt:
    """Secret-free result returned by a project-owned verifier."""

    verifier: str
    source_repository: str
    source_commit: str
    signer_identity: str
    subjects: Tuple[ArtifactVerificationSubject, ...]

    def __post_init__(self) -> None:
        if not self.verifier.strip():
            raise ArtifactVerificationError("artifact verifier identity is empty")
        if not self.source_repository.strip():
            raise ArtifactVerificationError(
                "artifact verification source repository is empty"
            )
        if SOURCE_COMMIT_PATTERN.fullmatch(self.source_commit) is None:
            raise ArtifactVerificationError(
                "artifact verification source commit is invalid"
            )
        if not self.signer_identity.strip():
            raise ArtifactVerificationError(
                "artifact verification signer identity is empty"
            )
        roles = [subject.role for subject in self.subjects]
        if len(roles) != len(set(roles)):
            raise ArtifactVerificationError(
                "artifact verification receipt contains duplicate subject roles"
            )

    def to_json(self) -> dict[str, Any]:
        """Return the safe, stable operator receipt shape."""
        return {
            "schema_version": VERIFICATION_RECEIPT_SCHEMA_VERSION,
            "verifier": self.verifier,
            "source_repository": self.source_repository,
            "source_commit": self.source_commit,
            "signer_identity": self.signer_identity,
            "subjects": [
                {
                    "role": subject.role,
                    "name": subject.name,
                    "sha256": subject.sha256,
                }
                for subject in self.subjects
            ],
        }


class ArtifactVerifier(Protocol):
    """Project-owned authentication boundary for an adoption artifact set."""

    def __call__(
        self,
        request: ArtifactVerificationRequest,
    ) -> ArtifactVerificationReceipt: ...


def artifact_verification_request(
    manifest: MigrationHistoryManifest,
) -> ArtifactVerificationRequest:
    """Build the exact generic request represented by one manifest."""
    return ArtifactVerificationRequest(
        artifact=manifest.artifact,
        manifest_sha256=manifest.content_sha256,
    )


def require_artifact_verification(
    verifier: ArtifactVerifier | None,
    request: ArtifactVerificationRequest,
) -> ArtifactVerificationReceipt:
    """Call and validate the required project-owned artifact verifier."""
    if not callable(verifier):
        raise ArtifactVerificationError(
            "project-owned artifact verifier is required for migration adoption"
        )
    try:
        receipt = verifier(request)
    except ArtifactVerificationError:
        raise
    except Exception as exc:
        raise ArtifactVerificationError(
            "project-owned artifact verifier failed with " + type(exc).__name__
        ) from exc
    if not isinstance(receipt, ArtifactVerificationReceipt):
        raise ArtifactVerificationError(
            "project-owned artifact verifier returned no valid receipt"
        )
    if receipt.source_commit != request.artifact.source_commit:
        raise ArtifactVerificationError(
            "artifact verification receipt source commit does not match"
        )
    _require_subject(
        receipt,
        role=SOURCE_ARTIFACT_ROLE,
        name=request.artifact.source_artifact,
        sha256=request.artifact.source_sha256,
    )
    _require_subject(
        receipt,
        role=MIGRATION_MANIFEST_ROLE,
        name=request.manifest_name,
        sha256=request.manifest_sha256,
    )
    return receipt


def _require_subject(
    receipt: ArtifactVerificationReceipt,
    *,
    role: str,
    name: str,
    sha256: str,
) -> None:
    subject = next(
        (candidate for candidate in receipt.subjects if candidate.role == role),
        None,
    )
    if subject is None:
        raise ArtifactVerificationError(
            f"artifact verification receipt is missing {role}"
        )
    if subject.name != name or subject.sha256 != sha256:
        raise ArtifactVerificationError(
            f"artifact verification receipt does not bind {role}"
        )


__all__ = [
    "ArtifactVerificationError",
    "ArtifactVerificationReceipt",
    "ArtifactVerificationRequest",
    "ArtifactVerificationSubject",
    "ArtifactVerifier",
    "MIGRATION_MANIFEST_ROLE",
    "SOURCE_ARTIFACT_ROLE",
    "VERIFICATION_RECEIPT_SCHEMA_VERSION",
    "artifact_verification_request",
    "require_artifact_verification",
]
