"""Artifact-bound manifest for permanent migration-history bytes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Tuple

from yoke_core.domain.migration_content_identity import (
    SHA256_PATTERN,
    raw_content_sha256,
)
from yoke_core.domain.migration_history import ENTRY_NAME_PATTERN, MigrationEntry


MANIFEST_SCHEMA_VERSION = 1
MIGRATION_HISTORY_MANIFEST_FILENAME = "migration-history.json"
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class MigrationHistoryManifestError(ValueError):
    """A migration-history manifest is malformed or bound elsewhere."""


@dataclass(frozen=True)
class ArtifactIdentity:
    """The immutable artifact whose migration bytes a manifest describes."""

    engine_version: str
    source_artifact: str
    source_sha256: str
    source_commit: str

    def __post_init__(self) -> None:
        if not self.engine_version.strip():
            raise MigrationHistoryManifestError("artifact engine_version is empty")
        if not self.source_artifact.strip():
            raise MigrationHistoryManifestError("artifact source_artifact is empty")
        if not SHA256_PATTERN.fullmatch(self.source_sha256):
            raise MigrationHistoryManifestError(
                "artifact source_sha256 must be a 64-character hex SHA256"
            )
        if not SOURCE_COMMIT_PATTERN.fullmatch(self.source_commit):
            raise MigrationHistoryManifestError(
                "artifact source_commit must be a full 40-character lowercase "
                "Git commit"
            )


@dataclass(frozen=True)
class ManifestEntry:
    name: str
    content_sha256: str


@dataclass(frozen=True)
class MigrationHistoryManifest:
    artifact: ArtifactIdentity
    entries: Tuple[ManifestEntry, ...]
    schema_version: int = MANIFEST_SCHEMA_VERSION

    @property
    def content_sha256(self) -> str:
        """Digest of the one deterministic byte representation of this manifest."""
        return raw_content_sha256(render_manifest(self))

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact": {
                "engine_version": self.artifact.engine_version,
                "source_artifact": self.artifact.source_artifact,
                "source_sha256": self.artifact.source_sha256,
                "source_commit": self.artifact.source_commit,
            },
            "entries": [
                {"name": entry.name, "content_sha256": entry.content_sha256}
                for entry in self.entries
            ],
        }


def manifest_from_history(
    history: Sequence[MigrationEntry],
    artifact: ArtifactIdentity,
) -> MigrationHistoryManifest:
    """Build a manifest from raw bytes represented by *history*."""
    return _manifest_from_digests(
        ((entry.name, entry.content_sha256) for entry in history), artifact
    )


def manifest_from_content(
    entries: Iterable[tuple[str, bytes]],
    artifact: ArtifactIdentity,
) -> MigrationHistoryManifest:
    """Build a manifest directly from named artifact member bytes."""
    return _manifest_from_digests(
        ((name, raw_content_sha256(content)) for name, content in entries),
        artifact,
    )


def _manifest_from_digests(
    entries: Iterable[tuple[str, str]],
    artifact: ArtifactIdentity,
) -> MigrationHistoryManifest:
    parsed = [ManifestEntry(str(name), str(digest)) for name, digest in entries]
    parsed.sort(key=lambda entry: int(entry.name.split("_", 1)[0]))
    _validate_entries(parsed)
    return MigrationHistoryManifest(artifact=artifact, entries=tuple(parsed))


def render_manifest(manifest: MigrationHistoryManifest) -> bytes:
    """Return the canonical bytes whose digest is recorded during adoption."""
    return (json.dumps(manifest.to_json(), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def write_manifest(path: Path, manifest: MigrationHistoryManifest) -> None:
    """Write deterministic JSON suitable for an immutable release directory."""
    path.write_bytes(render_manifest(manifest))


def load_manifest(
    path: Path,
    *,
    expected_artifact: ArtifactIdentity | None = None,
    expected_manifest_sha256: str | None = None,
) -> MigrationHistoryManifest:
    """Load canonical bytes, optionally pinning artifact and manifest identity."""
    try:
        manifest_bytes = path.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationHistoryManifestError(
            f"cannot read migration history manifest {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MigrationHistoryManifestError("manifest root must be an object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise MigrationHistoryManifestError(
            f"manifest schema_version must be {MANIFEST_SCHEMA_VERSION}"
        )
    artifact_payload = payload.get("artifact")
    if not isinstance(artifact_payload, dict):
        raise MigrationHistoryManifestError("manifest artifact must be an object")
    try:
        artifact = ArtifactIdentity(
            engine_version=str(artifact_payload["engine_version"]),
            source_artifact=str(artifact_payload["source_artifact"]),
            source_sha256=str(artifact_payload["source_sha256"]),
            source_commit=str(artifact_payload["source_commit"]),
        )
    except KeyError as exc:
        raise MigrationHistoryManifestError(
            f"manifest artifact is missing {exc.args[0]}"
        ) from exc
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise MigrationHistoryManifestError("manifest entries must be an array")
    entries: list[ManifestEntry] = []
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, Mapping):
            raise MigrationHistoryManifestError(
                f"manifest entry {index} must be an object"
            )
        try:
            entries.append(
                ManifestEntry(
                    name=str(raw_entry["name"]),
                    content_sha256=str(raw_entry["content_sha256"]),
                )
            )
        except KeyError as exc:
            raise MigrationHistoryManifestError(
                f"manifest entry {index} is missing {exc.args[0]}"
            ) from exc
    _validate_entries(entries)
    manifest = MigrationHistoryManifest(artifact=artifact, entries=tuple(entries))
    if manifest_bytes != render_manifest(manifest):
        raise MigrationHistoryManifestError(
            "migration history manifest is not in its deterministic serialization"
        )
    actual_manifest_sha256 = raw_content_sha256(manifest_bytes)
    if expected_manifest_sha256 is not None:
        if not SHA256_PATTERN.fullmatch(expected_manifest_sha256):
            raise MigrationHistoryManifestError(
                "expected manifest SHA256 must be a 64-character hex digest"
            )
        if actual_manifest_sha256 != expected_manifest_sha256.lower():
            raise MigrationHistoryManifestError(
                "migration history manifest SHA256 does not match the selected "
                "release evidence"
            )
    if expected_artifact is not None and artifact != expected_artifact:
        raise MigrationHistoryManifestError(
            "migration history manifest artifact identity does not match the "
            "selected artifact"
        )
    return manifest


def _validate_entries(entries: Sequence[ManifestEntry]) -> None:
    names: set[str] = set()
    previous = -1
    for entry in entries:
        match = ENTRY_NAME_PATTERN.fullmatch(entry.name)
        if match is None:
            raise MigrationHistoryManifestError(
                f"manifest entry name is invalid: {entry.name!r}"
            )
        if entry.name in names:
            raise MigrationHistoryManifestError(
                f"manifest entry is duplicated: {entry.name}"
            )
        if not SHA256_PATTERN.fullmatch(entry.content_sha256):
            raise MigrationHistoryManifestError(
                f"manifest digest for {entry.name} is not a SHA256"
            )
        sequence = int(match.group(1))
        if sequence <= previous:
            raise MigrationHistoryManifestError(
                "manifest entries are not in strictly increasing history order"
            )
        names.add(entry.name)
        previous = sequence


__all__ = [
    "ArtifactIdentity",
    "MANIFEST_SCHEMA_VERSION",
    "MIGRATION_HISTORY_MANIFEST_FILENAME",
    "ManifestEntry",
    "MigrationHistoryManifest",
    "MigrationHistoryManifestError",
    "SOURCE_COMMIT_PATTERN",
    "load_manifest",
    "manifest_from_content",
    "manifest_from_history",
    "render_manifest",
    "write_manifest",
]
