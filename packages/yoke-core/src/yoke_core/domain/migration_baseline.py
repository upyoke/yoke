"""Read an explicit, code-declared schema baseline without importing history."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_serving_version import (
    declared_minimum,
    ServingVersionError,
)


RELEASED_DIGESTS_NAME = "released_history_digests.json"


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
        if (
            value.keys()
            - required
            - {"predecessor_manifest", "adoption_evidence_table"}
        ):
            raise ValueError("unknown baseline fields")
        name, digest = value["name"], value["content_sha256"]
        if not ENTRY_NAME_PATTERN.fullmatch(name) or not SHA256_PATTERN.fullmatch(
            digest
        ):
            raise ValueError("invalid baseline name or digest")
        floor = declared_minimum(
            SimpleNamespace(MINIMUM_SERVING_VERSION=value["minimum_serving_version"])
        )
        predecessor = value.get("predecessor_manifest")
        if predecessor is not None and (
            Path(predecessor).name != predecessor or not predecessor.endswith(".json")
        ):
            raise ValueError("predecessor_manifest must be a local JSON filename")
        evidence = value.get("adoption_evidence_table")
        if predecessor and (
            not isinstance(evidence, str) or not evidence.isidentifier()
        ):
            raise ValueError("collapse requires its declared adoption_evidence_table")
        return MigrationEntry(
            sequence=int(name.split("_", 1)[0]),
            name=name,
            path=directory / "__init__.py",
            minimum_serving_version=floor,
            baseline_content_sha256=digest,
            baseline_predecessors=directory / predecessor if predecessor else None,
            baseline_evidence_table=evidence,
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
