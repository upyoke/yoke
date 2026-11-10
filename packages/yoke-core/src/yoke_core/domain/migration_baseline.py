"""Read an explicit, code-declared schema baseline without importing history."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_serving_version import (
    declared_minimum,
    ServingVersionError,
    NEXT_RELEASE,
)


def baseline_from_source(raw: bytes, directory: Path):
    from yoke_core.domain.migration_history import (
        ENTRY_NAME_PATTERN,
        HistoryError,
        MigrationEntry,
    )

    declarations = [
        node.value
        for node in ast.parse(raw).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "HISTORY_BASELINE" for t in node.targets
        )
    ]
    if not declarations:
        return None
    if len(declarations) != 1:
        raise HistoryError("migration_baseline_invalid: declare HISTORY_BASELINE once")
    try:
        value = ast.literal_eval(declarations[0])
        required = {"name", "content_sha256", "minimum_serving_version"}
        if not isinstance(value, dict) or not required <= value.keys():
            raise ValueError("missing baseline identity")
        if value.keys() - required:
            raise ValueError("unknown baseline fields")
        name, digest = value["name"], value["content_sha256"]
        if not ENTRY_NAME_PATTERN.fullmatch(name) or not SHA256_PATTERN.fullmatch(
            digest
        ):
            raise ValueError("invalid baseline name or digest")
        floor = declared_minimum(
            SimpleNamespace(MINIMUM_SERVING_VERSION=value["minimum_serving_version"])
        )
        return MigrationEntry(
            sequence=int(name.split("_", 1)[0]),
            name=name,
            path=directory / "__init__.py",
            minimum_serving_version=floor,
            baseline_content_sha256=digest,
        )
    except (ValueError, TypeError, KeyError, ServingVersionError) as exc:
        raise HistoryError(
            f"migration_baseline_invalid: {exc}; restore the declared baseline identity"
        ) from exc


def declared_baseline(directory: Path):
    source = directory / "__init__.py"
    return (
        baseline_from_source(source.read_bytes(), directory)
        if source.is_file()
        else None
    )


def baseline_recorded_floor(entry, running_version: str) -> str | None:
    floor = entry.minimum_serving_version
    return running_version.strip() or None if floor == NEXT_RELEASE else floor
