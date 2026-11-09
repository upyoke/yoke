"""Frozen metadata for scripts folded into the current baseline schema.

The existing released digest map keeps string values for live content pins.
An object value denotes a folded entry and includes its serving floor (null
when no floor was declared). No script may share its name or ordinal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
from types import SimpleNamespace

from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_serving_version import (
    NEXT_RELEASE,
    declared_minimum,
    ServingVersionError,
)

RELEASED_DIGESTS_NAME = "released_history_digests.json"


def parse_released_digests(raw: bytes) -> dict[str, Any]:
    from yoke_core.domain.migration_history import ENTRY_NAME_PATTERN, HistoryError

    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise HistoryError(
            "migration_folded_history_invalid: cannot read released digest map; "
            "restore valid released_history_digests.json"
        ) from exc
    if not isinstance(payload, dict):
        raise HistoryError("released migration digests must be a name-to-identity map")
    for name, value in payload.items():
        valid = bool(ENTRY_NAME_PATTERN.fullmatch(name))
        digest = value
        if isinstance(value, dict):
            valid &= set(value) == {"content_sha256", "minimum_serving_version"}
            digest = value.get("content_sha256")
            floor = value.get("minimum_serving_version")
            valid &= floor is None or (
                isinstance(floor, str) and bool(floor.strip()) and floor != NEXT_RELEASE
            )
            try:
                valid &= (
                    declared_minimum(SimpleNamespace(MINIMUM_SERVING_VERSION=floor))
                    != NEXT_RELEASE
                )
            except ServingVersionError:
                valid = False
        if (
            not valid
            or not isinstance(digest, str)
            or not SHA256_PATTERN.fullmatch(digest)
        ):
            raise HistoryError(
                f"migration_folded_history_invalid: invalid identity for {name}; "
                "restore its released SHA256 and resolved minimum_serving_version"
            )
    return payload


def folded_entries_from_bytes(raw: bytes, directory: Path):
    from yoke_core.domain.migration_history import MigrationEntry

    return tuple(
        MigrationEntry(
            sequence=int(name.split("_", 1)[0]),
            name=name,
            path=directory / f"{name}.py",
            folded_content_sha256=value["content_sha256"].lower(),
            minimum_serving_version=value["minimum_serving_version"],
        )
        for name, value in parse_released_digests(raw).items()
        if isinstance(value, dict)
    )


def folded_entries(directory: Path):
    manifest = directory / RELEASED_DIGESTS_NAME
    if not manifest.is_file():
        return ()
    return folded_entries_from_bytes(manifest.read_bytes(), directory)


def require_folded_membership(history: Sequence, recorded: set[str]) -> None:
    from yoke_core.domain.migration_history import HistoryError

    missing = [
        entry.name
        for entry in history
        if entry.is_folded and entry.name not in recorded
    ]
    if missing:
        raise HistoryError(
            "migration_folded_history_missing: database lacks folded migrations: "
            + ", ".join(missing)
            + ". Upgrade using an earlier build carrying these scripts first, "
            "then retry this build. An existing pre-ledger database with no rows "
            "must take that same upgrade path; only a caller-observed new database "
            "may stamp the baseline."
        )
