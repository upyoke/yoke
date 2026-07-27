"""DB-independent validation for committed migration manifests."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from yoke_core.domain.db_compatibility_attestation import (
    AUTHORED_FIELDS,
    validate as validate_attestation,
)
from yoke_core.domain.db_mutation_profile import (
    MUTATION_INTENT_APPLY,
    STATE_DECLARED,
    validate as validate_profile,
)
from yoke_core.domain.migration_apply_contract import MigrationApplyError

MANIFEST_VERSION = 1
_TOP_LEVEL_KEYS = frozenset(
    {"version", "project", "profile", "attestation", "module_sources"}
)
_MODULE_SOURCE_KEYS = frozenset({"path", "sha256"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


class MigrationManifestError(MigrationApplyError):
    """An itemless migration manifest or its source checkout is unsafe."""


def validate_manifest_payload(
    payload: Any,
) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    """Validate the DB-independent theorem carried by a manifest payload."""
    if not isinstance(payload, dict):
        raise MigrationManifestError("migration manifest root must be an object")
    unknown = set(payload) - _TOP_LEVEL_KEYS
    missing = _TOP_LEVEL_KEYS - set(payload)
    if unknown or missing:
        raise MigrationManifestError(
            f"migration manifest keys invalid; missing={sorted(missing)} "
            f"unknown={sorted(unknown)}"
        )
    if payload.get("version") != MANIFEST_VERSION:
        raise MigrationManifestError(
            f"migration manifest version must be {MANIFEST_VERSION}"
        )

    project = payload.get("project")
    if not isinstance(project, str) or not project.strip():
        raise MigrationManifestError("migration manifest project must be non-empty")
    project = project.strip()
    try:
        profile = validate_profile(payload.get("profile"))
        attestation = validate_attestation(payload.get("attestation"))
    except ValueError as exc:
        raise MigrationManifestError(
            f"migration manifest theorem invalid: {exc}"
        ) from exc
    if profile.get("state") != STATE_DECLARED:
        raise MigrationManifestError("migration manifest profile must be declared")
    if profile.get("mutation_intent") != MUTATION_INTENT_APPLY:
        raise MigrationManifestError("migration manifest profile intent must be apply")
    missing_attestations = sorted(
        field for field in AUTHORED_FIELDS if not attestation.get(field)
    )
    if missing_attestations:
        raise MigrationManifestError(
            "migration manifest attestation has empty authored fields: "
            + ", ".join(missing_attestations)
        )
    manifest_module_sources(payload, profile)
    return project, profile, attestation


def manifest_module_sources(
    payload: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> Mapping[str, Mapping[str, str]]:
    """Validate the source path and digest bound to every module slug."""
    raw = payload.get("module_sources")
    if not isinstance(raw, dict):
        raise MigrationManifestError(
            "migration manifest module_sources must be an object"
        )
    expected = {str(identifier) for identifier in profile["migration_modules"]}
    actual = set(raw)
    if actual != expected:
        raise MigrationManifestError(
            "migration manifest module_sources must exactly match migration_modules; "
            f"missing={sorted(expected - actual)} unknown={sorted(actual - expected)}"
        )
    normalized: dict[str, Mapping[str, str]] = {}
    for identifier in sorted(expected):
        source = raw[identifier]
        if not isinstance(source, dict) or set(source) != _MODULE_SOURCE_KEYS:
            raise MigrationManifestError(
                f"migration manifest module source {identifier!r} must contain only "
                "path and sha256"
            )
        path_raw = source.get("path")
        if not isinstance(path_raw, str) or not path_raw.strip():
            raise MigrationManifestError(
                f"migration manifest module source {identifier!r} has no path"
            )
        path = PurePosixPath(path_raw)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != path_raw
            or path.name != f"{identifier}.py"
        ):
            raise MigrationManifestError(
                f"migration manifest module source {identifier!r} path is unsafe"
            )
        digest = source.get("sha256")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise MigrationManifestError(
                f"migration manifest module source {identifier!r} sha256 is invalid"
            )
        normalized[identifier] = {"path": path.as_posix(), "sha256": digest}
    return normalized


__all__ = [
    "MANIFEST_VERSION",
    "MigrationManifestError",
    "manifest_module_sources",
    "validate_manifest_payload",
]
