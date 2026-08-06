"""Trusted manifest parsing for legacy migration-content adoption."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from packaging.version import InvalidVersion, Version


MANIFEST_SCHEMA = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def module_sha256(entry, *, source_bytes: bytes | None = None) -> str:
    """Hash the exact bytes stored for one permanent migration module."""
    content = entry.path.read_bytes() if source_bytes is None else source_bytes
    return hashlib.sha256(content).hexdigest()


def minimum_serving_version(module) -> str | None:
    """Return and validate an entry's oldest compatible artifact version."""
    raw = getattr(module, "MINIMUM_SERVING_VERSION", None)
    if raw is None or not str(raw).strip():
        return None
    value = str(raw).strip()
    try:
        Version(value)
    except InvalidVersion as exc:
        raise RuntimeError(f"MINIMUM_SERVING_VERSION is invalid: {value!r}") from exc
    return value


def validated_running_version(running_version: str) -> str:
    value = str(running_version).strip()
    if not value:
        raise RuntimeError("non-empty running artifact version is required")
    try:
        Version(value)
    except InvalidVersion as exc:
        raise RuntimeError(f"Invalid running artifact version: {value!r}") from exc
    return value


def refuse_old_build(name: str, running_version: str, floor: str | None) -> None:
    running_version = validated_running_version(running_version)
    if not floor:
        return
    try:
        safe = Version(running_version) >= Version(floor)
    except InvalidVersion as exc:
        raise RuntimeError(
            f"Cannot compare build {running_version!r} with {name} floor {floor!r}"
        ) from exc
    if not safe:
        raise RuntimeError(
            f"Migration {name} requires build {floor} or newer; this build is "
            f"{running_version}"
        )


def canonical_manifest_sha256(raw: dict) -> str:
    """Digest the semantic manifest payload, excluding its digest field."""
    payload = {key: raw[key] for key in ("schema_version", "artifact", "entries")}
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
        raise RuntimeError(
            "Migration adoption manifest_sha256 must be lowercase SHA256"
        )
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
    artifact,
    *,
    source_commit: str,
    trusted_source_sha256: str,
) -> dict[str, str]:
    keys = {
        "engine_version",
        "source_artifact",
        "source_sha256",
        "source_commit",
    }
    if not isinstance(artifact, dict) or set(artifact) != keys:
        raise RuntimeError(
            "Migration adoption artifact requires only engine_version, "
            "source_artifact, source_sha256, and source_commit"
        )
    if (
        not isinstance(artifact["engine_version"], str)
        or not artifact["engine_version"].strip()
    ):
        raise RuntimeError(
            "Migration adoption artifact engine_version must be non-empty"
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
    if not isinstance(artifact_source_sha256, str) or not SHA256_RE.fullmatch(
        artifact_source_sha256
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
    path,
    history,
    *,
    source_commit: str,
    source_sha256: str,
    manifest_sha256: str,
) -> dict:
    """Validate an audited history subset and its immutable artifact."""
    raw = _read_json(path, manifest_sha256)
    if raw["schema_version"] != MANIFEST_SCHEMA:
        raise RuntimeError(
            f"Migration adoption manifest requires schema_version {MANIFEST_SCHEMA}"
        )
    artifact = _validate_artifact(
        raw["artifact"],
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
    history_names = [entry.name for entry in history]
    unknown = [name for name in ordered_names if name not in history_names]
    expected_order = [name for name in history_names if name in entries]
    if unknown or ordered_names != expected_order:
        raise RuntimeError(
            "Adoption manifest entries must be an ordered subset of current "
            f"migration history; unknown={unknown!r}, supplied={ordered_names!r}"
        )
    for entry in history:
        if entry.name not in entries:
            continue
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


def verify_artifact_evidence(manifest, verifier) -> dict:
    """Require a project-owned verifier receipt bound to this manifest."""
    if not callable(verifier):
        raise RuntimeError(
            "Migration adoption requires a project-owned artifact evidence verifier"
        )
    result = verifier(manifest)
    required = {
        "verifier",
        "source_artifact",
        "source_sha256",
        "source_commit",
        "manifest_sha256",
        "verification_receipt_sha256",
    }
    if not isinstance(result, Mapping) or set(result) != required:
        raise RuntimeError(
            "Artifact evidence verifier must return the exact bound receipt fields"
        )
    artifact = manifest["artifact"]
    expected = {
        "source_artifact": artifact["source_artifact"],
        "source_sha256": artifact["source_sha256"],
        "source_commit": artifact["source_commit"],
        "manifest_sha256": manifest["manifest_sha256"],
    }
    mismatched = [name for name, value in expected.items() if result[name] != value]
    verifier_name = str(result["verifier"] or "").strip()
    receipt_digest = str(result["verification_receipt_sha256"] or "").strip()
    if mismatched or not verifier_name or not SHA256_RE.fullmatch(receipt_digest):
        raise RuntimeError(
            "Artifact evidence receipt does not bind the selected adoption "
            f"artifact; mismatched={mismatched!r}"
        )
    return dict(result)


__all__ = [
    "SHA256_RE",
    "canonical_manifest_sha256",
    "minimum_serving_version",
    "module_sha256",
    "read_adoption_manifest",
    "refuse_old_build",
    "validated_running_version",
    "verify_artifact_evidence",
]
