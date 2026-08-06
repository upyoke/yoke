"""Generate and verify Yoke's migration manifest from the built core wheel."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Sequence

from yoke_core.domain.migration_history import ENTRY_NAME_PATTERN
from yoke_core.domain.migration_history import MigrationEntry, ordered_entries
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    MIGRATION_HISTORY_MANIFEST_FILENAME,
    MigrationHistoryManifest,
    MigrationHistoryManifestError,
    load_manifest,
    manifest_from_content,
    write_manifest,
)
from yoke_core.tools import package_index
from yoke_core.tools.package_index import WheelRecord


CORE_PROJECT = "yoke-core"
CORE_HISTORY_PREFIX = "yoke_core/domain/migrations/"
MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME = "migration-history-record.json"
RELEASE_EVIDENCE_SCHEMA_VERSION = 1


def manifest_for_core_wheel(
    records: Sequence[WheelRecord],
    *,
    source_commit: str,
) -> MigrationHistoryManifest:
    """Build the manifest from bytes inside the selected release wheel."""
    record = _core_record(records)
    artifact = ArtifactIdentity(
        engine_version=record.version,
        source_artifact=record.filename,
        source_sha256=record.sha256,
        source_commit=source_commit,
    )
    return manifest_from_content(_wheel_history(record.source), artifact)


def manifest_for_core_wheel_path(
    wheel: Path,
    *,
    source_commit: str,
) -> MigrationHistoryManifest:
    """Build a manifest from one exact core wheel selected by an operator."""
    record = package_index.read_wheel_record(wheel)
    return manifest_for_core_wheel((record,), source_commit=source_commit)


def write_release_manifest(
    path: Path,
    records: Sequence[WheelRecord],
    *,
    source_commit: str,
) -> MigrationHistoryManifest:
    manifest = manifest_for_core_wheel(records, source_commit=source_commit)
    write_manifest(path, manifest)
    return manifest


def release_evidence(manifest: MigrationHistoryManifest) -> dict[str, object]:
    """Record independently attestable manifest and source provenance."""
    artifact = manifest.artifact
    return {
        "schema_version": RELEASE_EVIDENCE_SCHEMA_VERSION,
        "manifest": {
            "filename": MIGRATION_HISTORY_MANIFEST_FILENAME,
            "sha256": manifest.content_sha256,
        },
        "artifact": {
            "engine_version": artifact.engine_version,
            "source_artifact": artifact.source_artifact,
            "source_sha256": artifact.source_sha256,
            "source_commit": artifact.source_commit,
        },
    }


def write_release_evidence(
    path: Path,
    manifest: MigrationHistoryManifest,
) -> dict[str, object]:
    """Write the record attested and published beside the manifest."""
    payload = release_evidence(manifest)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def validate_release_evidence(
    path: Path,
    manifest: MigrationHistoryManifest,
    *,
    expected_source_commit: str | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, object]:
    """Require the published/attested record to bind the selected manifest."""
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationHistoryManifestError(
            f"cannot read migration history release evidence {path}: {exc}"
        ) from exc
    expected = release_evidence(manifest)
    canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if raw != canonical:
        raise MigrationHistoryManifestError(
            "migration history release evidence is not deterministic JSON"
        )
    if payload != expected:
        raise MigrationHistoryManifestError(
            "migration history release evidence does not bind the selected "
            "manifest and artifact"
        )
    artifact = manifest.artifact
    if (
        expected_source_commit is not None
        and artifact.source_commit != expected_source_commit
    ):
        raise MigrationHistoryManifestError(
            "migration history release evidence source commit does not match"
        )
    if (
        expected_manifest_sha256 is not None
        and manifest.content_sha256 != expected_manifest_sha256.lower()
    ):
        raise MigrationHistoryManifestError(
            "migration history release evidence manifest SHA256 does not match"
        )
    return payload


def validate_release_manifest(
    path: Path,
    records: Sequence[WheelRecord],
    *,
    expected_source_commit: str | None = None,
    expected_manifest_sha256: str | None = None,
) -> MigrationHistoryManifest:
    """Require the release manifest to match the exact built core wheel."""
    loaded = load_manifest(
        path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if (
        expected_source_commit is not None
        and loaded.artifact.source_commit != expected_source_commit
    ):
        raise MigrationHistoryManifestError(
            "migration history manifest source commit does not match the "
            "selected release"
        )
    expected = manifest_for_core_wheel(
        records,
        source_commit=loaded.artifact.source_commit,
    )
    if loaded != expected:
        raise MigrationHistoryManifestError(
            "migration history manifest entries do not match the core wheel"
        )
    return loaded


def materialize_core_wheel_history(
    wheel: Path,
    destination: Path,
) -> tuple[MigrationEntry, ...]:
    """Extract only validated history members from *wheel* into *destination*."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in _wheel_history(wheel):
        (destination / f"{name}.py").write_bytes(content)
    return ordered_entries(destination)


def _core_record(records: Sequence[WheelRecord]) -> WheelRecord:
    matches = [record for record in records if record.canonical_name == CORE_PROJECT]
    if len(matches) != 1:
        raise MigrationHistoryManifestError(
            "release must contain exactly one yoke-core wheel for its migration "
            "history manifest"
        )
    return matches[0]


def _wheel_history(wheel: Path) -> tuple[tuple[str, bytes], ...]:
    found: list[tuple[int, str, bytes]] = []
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
            if not member.startswith(CORE_HISTORY_PREFIX) or not member.endswith(".py"):
                continue
            relative = member[len(CORE_HISTORY_PREFIX) :]
            if "/" in relative:
                continue
            stem = Path(relative).stem
            if stem.startswith(("_", "test_")):
                continue
            match = ENTRY_NAME_PATTERN.fullmatch(stem)
            if match is None:
                raise MigrationHistoryManifestError(
                    f"core wheel contains invalid migration entry {relative!r}"
                )
            found.append((int(match.group(1)), stem, archive.read(member)))
    if not found:
        raise MigrationHistoryManifestError(
            "core wheel contains no permanent migration history entries"
        )
    found.sort(key=lambda item: item[0])
    sequences = [item[0] for item in found]
    if len(sequences) != len(set(sequences)):
        raise MigrationHistoryManifestError(
            "core wheel migration history contains duplicate sequences"
        )
    return tuple((name, content) for _sequence, name, content in found)


__all__ = [
    "CORE_HISTORY_PREFIX",
    "CORE_PROJECT",
    "MIGRATION_HISTORY_MANIFEST_FILENAME",
    "MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME",
    "RELEASE_EVIDENCE_SCHEMA_VERSION",
    "manifest_for_core_wheel_path",
    "manifest_for_core_wheel",
    "materialize_core_wheel_history",
    "release_evidence",
    "validate_release_manifest",
    "validate_release_evidence",
    "write_release_evidence",
    "write_release_manifest",
]
