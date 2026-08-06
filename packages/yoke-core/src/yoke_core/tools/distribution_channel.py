"""Versioned public distribution-channel payloads and URL helpers."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_history_manifest import SOURCE_COMMIT_PATTERN
from yoke_core.tools import migration_history_release_artifact


CHANNELS = ("stable", "latest")
LEGACY_CHANNEL_SCHEMA_VERSION = 2
CONTENT_CHANNEL_SCHEMA_VERSION = 3
INSTALL_PY = "install.py"
INSTALL_SHIM = "install"
MIGRATION_HISTORY_MANIFEST_FILENAME = (
    migration_history_release_artifact.MIGRATION_HISTORY_MANIFEST_FILENAME
)
MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME = (
    migration_history_release_artifact.MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME
)


def channel_payload(
    *,
    channel: str,
    version: str,
    index_url: str,
    release_base_url: str,
    generated_at: str,
    migration_manifest_sha256: str,
    source_commit: str,
    site_root: str | None = None,
) -> dict[str, object]:
    if channel not in CHANNELS:
        raise ValueError("channel must be stable or latest")
    if not SHA256_PATTERN.fullmatch(migration_manifest_sha256):
        raise ValueError("migration manifest SHA256 must be a 64-character digest")
    if not SOURCE_COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("migration source commit must be a full lowercase Git SHA")
    root = site_root or site_root_from_release_base(release_base_url)
    payload = {
        "schema_version": CONTENT_CHANNEL_SCHEMA_VERSION,
        "channel": channel,
        "version": version,
        "generated_at": generated_at,
        "index_url": index_url,
        "release_base_url": release_base_url,
        "migration_history": {
            "manifest_url": join_public_url(
                release_base_url,
                MIGRATION_HISTORY_MANIFEST_FILENAME,
            ),
            "evidence_url": join_public_url(
                release_base_url,
                MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME,
            ),
            "manifest_sha256": migration_manifest_sha256.lower(),
            "source_commit": source_commit,
        },
        "installer": {
            "python_url": urljoin(root, f"dist/{INSTALL_PY}"),
            "shell_url": urljoin(root, INSTALL_SHIM),
        },
    }
    validate_channel_pointer(payload, require_content_evidence=True)
    return payload


def validate_channel_pointer(
    payload: Mapping[str, object],
    *,
    require_content_evidence: bool = False,
) -> None:
    """Accept historical v2 pointers and fail closed for content-aware v3."""
    schema_version = payload.get("schema_version")
    if schema_version == LEGACY_CHANNEL_SCHEMA_VERSION:
        if require_content_evidence:
            raise ValueError(
                "legacy channel schema v2 has no trusted migration content evidence"
            )
        return
    if schema_version != CONTENT_CHANNEL_SCHEMA_VERSION:
        raise ValueError("channel schema_version must be 2 or 3")
    migration_history = payload.get("migration_history")
    if not isinstance(migration_history, Mapping):
        raise ValueError(
            "content-aware channel schema v3 lacks migration_history evidence"
        )
    manifest_sha256 = str(migration_history.get("manifest_sha256") or "")
    source_commit = str(migration_history.get("source_commit") or "")
    manifest_url = str(migration_history.get("manifest_url") or "")
    evidence_url = str(migration_history.get("evidence_url") or "")
    if not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise ValueError("channel migration manifest SHA256 is invalid")
    if not SOURCE_COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("channel migration source commit is invalid")
    if not manifest_url.endswith(f"/{MIGRATION_HISTORY_MANIFEST_FILENAME}"):
        raise ValueError("channel migration manifest URL is invalid")
    if not evidence_url.endswith(f"/{MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME}"):
        raise ValueError("channel migration release-evidence URL is invalid")


def site_root_from_release_base(base_url: str) -> str:
    marker = "/dist/releases/"
    if marker not in base_url:
        return base_url.rstrip("/") + "/"
    return base_url.split(marker, 1)[0].rstrip("/") + "/"


def join_public_url(base: str, *parts: str) -> str:
    value = quote_url_path(base.rstrip("/"))
    for part in parts:
        value += "/" + quote(part.strip("/"), safe="%")
    return value


def quote_url_path(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            quote(parsed.path, safe="/%"),
            parsed.query,
            parsed.fragment,
        )
    )
