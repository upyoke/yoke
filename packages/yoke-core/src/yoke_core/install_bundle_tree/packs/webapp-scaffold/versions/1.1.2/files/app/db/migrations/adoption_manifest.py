"""Trusted manifest parsing for legacy migration-content adoption."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


MANIFEST_SCHEMA = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def module_sha256(entry) -> str:
    """Hash the exact bytes stored for one permanent migration module."""
    return hashlib.sha256(entry.path.read_bytes()).hexdigest()


def canonical_manifest_sha256(raw: dict) -> str:
    """Digest the semantic manifest payload, excluding its digest field."""
    payload = {
        key: raw[key]
        for key in ("schema_version", "artifact", "entries")
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path, trusted_manifest_sha256: str) -> dict:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise RuntimeError(f"Migration adoption manifest not found: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid migration adoption manifest: {exc}") from exc
    required = {"schema_version", "artifact", "entries", "manifest_sha256"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise RuntimeError(
            "Migration adoption manifest must contain only schema_version, "
            "artifact, entries, and manifest_sha256"
        )
    supplied = raw["manifest_sha256"]
    if not isinstance(supplied, str) or not SHA256_RE.fullmatch(supplied):
        raise RuntimeError("Migration adoption manifest_sha256 must be lowercase SHA256")
    expected = canonical_manifest_sha256(raw)
    if supplied != expected:
        raise RuntimeError(
            "Migration adoption manifest_sha256 does not match the canonical payload"
        )
    trusted = str(trusted_manifest_sha256 or "").strip()
    if not SHA256_RE.fullmatch(trusted):
        raise RuntimeError("A trusted lowercase manifest SHA256 is required")
    if trusted != expected:
        raise RuntimeError(
            "Trusted manifest SHA256 does not match the canonical payload"
        )
    return raw


def _validate_artifact(
    artifact, *, running_version: str, source_commit: str,
    trusted_source_sha256: str,
) -> dict[str, str]:
    keys = {
        "engine_version", "source_artifact", "source_sha256", "source_commit",
    }
    if not isinstance(artifact, dict) or set(artifact) != keys:
        raise RuntimeError(
            "Migration adoption artifact requires only engine_version, "
            "source_artifact, source_sha256, and source_commit"
        )
    if artifact["engine_version"] != running_version:
        raise RuntimeError(
            "Migration adoption artifact engine_version does not match the "
            "running artifact version"
        )
    trusted_commit = str(source_commit or "").strip()
    if not SOURCE_COMMIT_RE.fullmatch(trusted_commit):
        raise RuntimeError(
            "A trusted 40- or 64-character lowercase source commit is required"
        )
    manifest_commit = artifact["source_commit"]
    if not isinstance(manifest_commit, str) or not SOURCE_COMMIT_RE.fullmatch(
        manifest_commit
    ):
        raise RuntimeError(
            "Migration adoption source_commit must be 40 or 64 lowercase hex"
        )
    if manifest_commit != trusted_commit:
        raise RuntimeError(
            "Migration adoption source_commit does not match the trusted artifact"
        )
    source_artifact = artifact["source_artifact"]
    if (
        not isinstance(source_artifact, str)
        or not source_artifact
        or source_artifact != source_artifact.strip()
    ):
        raise RuntimeError("Migration adoption source_artifact must be non-empty")
    artifact_source_sha256 = artifact["source_sha256"]
    if (
        not isinstance(artifact_source_sha256, str)
        or not SHA256_RE.fullmatch(artifact_source_sha256)
    ):
        raise RuntimeError("Migration adoption source_sha256 must be lowercase SHA256")
    trusted_digest = str(trusted_source_sha256 or "").strip()
    if not SHA256_RE.fullmatch(trusted_digest):
        raise RuntimeError("A trusted lowercase source artifact SHA256 is required")
    if artifact_source_sha256 != trusted_digest:
        raise RuntimeError(
            "Migration adoption source_sha256 does not match the trusted artifact"
        )
    return artifact


def read_adoption_manifest(
    path, history, *, running_version: str, source_commit: str,
    source_sha256: str, manifest_sha256: str,
) -> dict:
    """Validate artifact identity, canonical digest, order, and exact bytes."""
    raw = _read_json(path, manifest_sha256)
    if raw["schema_version"] != MANIFEST_SCHEMA:
        raise RuntimeError(
            f"Migration adoption manifest requires schema_version {MANIFEST_SCHEMA}"
        )
    artifact = _validate_artifact(
        raw["artifact"],
        running_version=running_version,
        source_commit=source_commit,
        trusted_source_sha256=source_sha256,
    )
    if not isinstance(raw["entries"], list):
        raise RuntimeError("Migration adoption entries must be a list")
    entries = {}
    ordered_names = []
    for item in raw["entries"]:
        if not isinstance(item, dict) or set(item) != {"name", "content_sha256"}:
            raise RuntimeError(
                "Each adoption entry requires only name and content_sha256"
            )
        name, digest = item["name"], item["content_sha256"]
        if not isinstance(name, str) or not name or name != name.strip():
            raise RuntimeError("Adoption manifest migration name must be non-empty")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise RuntimeError(
                f"Adoption manifest digest for {name!r} must be lowercase SHA256"
            )
        if name in entries:
            raise RuntimeError(f"Adoption manifest repeats migration {name!r}")
        entries[name] = digest
        ordered_names.append(name)
    expected_names = [entry.name for entry in history]
    if ordered_names != expected_names:
        raise RuntimeError(
            "Adoption manifest entries must exactly match ordered migration history; "
            f"expected={expected_names!r}, supplied={ordered_names!r}"
        )
    for entry in history:
        if entries[entry.name] != module_sha256(entry):
            raise RuntimeError(
                f"Adoption manifest digest for {entry.name!r} does not match "
                "the exact migration module bytes"
            )
    return {
        "artifact": artifact,
        "entries": entries,
        "manifest_sha256": raw["manifest_sha256"],
    }


__all__ = [
    "SHA256_RE",
    "canonical_manifest_sha256",
    "module_sha256",
    "read_adoption_manifest",
]
