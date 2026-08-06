"""Verify local artifact bytes through GitHub's attestation trust root."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from yoke_core.domain.github_actions_identifiers import repository_api_path
from yoke_core.domain.migration_artifact_trust import (
    ArtifactVerificationError,
    ArtifactVerificationReceipt,
    ArtifactVerificationRequest,
    ArtifactVerificationSubject,
    require_artifact_verification,
)
from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_history_manifest import SOURCE_COMMIT_PATTERN


GITHUB_ATTESTATION_VERIFIER = "github-cli-attestation/v1"


@dataclass(frozen=True)
class GitHubAttestationSubject:
    """Local subject path and the receipt role it must satisfy."""

    role: str
    path: Path


@dataclass
class GitHubArtifactAttestationVerifier:
    """Authenticate an exact subject set with one GitHub signer policy."""

    repository: str
    source_commit: str
    signer_workflow: str
    subjects: Sequence[GitHubAttestationSubject]
    executable: str = "gh"
    _cached_request: ArtifactVerificationRequest | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _cached_receipt: ArtifactVerificationReceipt | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        repository_api_path(self.repository)
        if SOURCE_COMMIT_PATTERN.fullmatch(self.source_commit) is None:
            raise ArtifactVerificationError(
                "GitHub attestation source commit must be a full lowercase SHA"
            )
        if not self.signer_workflow.strip():
            raise ArtifactVerificationError(
                "GitHub attestation signer workflow is empty"
            )
        self.subjects = tuple(self.subjects)
        roles = [subject.role for subject in self.subjects]
        if not roles or len(roles) != len(set(roles)):
            raise ArtifactVerificationError(
                "GitHub attestation subjects must have unique non-empty roles"
            )

    def __call__(
        self,
        request: ArtifactVerificationRequest,
    ) -> ArtifactVerificationReceipt:
        if self._cached_request is not None:
            if request != self._cached_request or self._cached_receipt is None:
                raise ArtifactVerificationError(
                    "GitHub attestation verifier cannot be reused for another release"
                )
            return self._cached_receipt
        if request.artifact.source_commit != self.source_commit:
            raise ArtifactVerificationError(
                "GitHub attestation source commit does not match the artifact"
            )
        executable = _resolve_executable(self.executable)
        verified: list[ArtifactVerificationSubject] = []
        for subject in self.subjects:
            if not subject.path.is_file():
                raise ArtifactVerificationError(
                    f"GitHub attestation subject is missing: {subject.role}"
                )
            completed = _run_verification(
                (
                    executable,
                    "attestation",
                    "verify",
                    str(subject.path),
                    "--repo",
                    self.repository,
                    "--signer-workflow",
                    self.signer_workflow,
                    "--source-digest",
                    self.source_commit,
                    "--deny-self-hosted-runners",
                    "--format",
                    "json",
                )
            )
            if completed.returncode != 0:
                raise ArtifactVerificationError(
                    "GitHub attestation verification failed for "
                    f"{subject.role} (exit {completed.returncode})"
                )
            verified.append(
                ArtifactVerificationSubject(
                    role=subject.role,
                    name=subject.path.name,
                    sha256=_verified_subject_sha256(
                        completed.stdout,
                        subject.path.name,
                    ),
                )
            )
        receipt = ArtifactVerificationReceipt(
            verifier=GITHUB_ATTESTATION_VERIFIER,
            source_repository=self.repository,
            source_commit=self.source_commit,
            signer_identity=self.signer_workflow,
            subjects=tuple(verified),
        )
        require_artifact_verification(lambda _request: receipt, request)
        self._cached_request = request
        self._cached_receipt = receipt
        return receipt


def _resolve_executable(executable: str) -> str:
    selected = shutil.which(executable)
    if selected is None:
        raise ArtifactVerificationError(
            "GitHub CLI with attestation verification support is required"
        )
    return selected


def _run_verification(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArtifactVerificationError(
            "GitHub attestation verification command could not complete"
        ) from exc


def _verified_subject_sha256(output: str, filename: str) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ArtifactVerificationError(
            "GitHub attestation verifier returned malformed JSON"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise ArtifactVerificationError(
            "GitHub attestation verifier returned no verified attestations"
        )
    digests: set[str] = set()
    for result in payload:
        if not isinstance(result, dict):
            continue
        verification = result.get("verificationResult")
        statement = (
            verification.get("statement") if isinstance(verification, dict) else None
        )
        subjects = statement.get("subject") if isinstance(statement, dict) else None
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            if not isinstance(subject, dict):
                continue
            name = str(subject.get("name") or "")
            digest = subject.get("digest")
            sha256 = digest.get("sha256") if isinstance(digest, dict) else None
            if Path(name).name == filename and isinstance(sha256, str):
                if SHA256_PATTERN.fullmatch(sha256):
                    digests.add(sha256.lower())
    if len(digests) != 1:
        raise ArtifactVerificationError(
            "GitHub attestation verifier did not return one exact subject digest"
        )
    return next(iter(digests))


__all__ = [
    "GITHUB_ATTESTATION_VERIFIER",
    "GitHubArtifactAttestationVerifier",
    "GitHubAttestationSubject",
]
