"""Native clock custody for regenerable relay probe caches."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.timestamps import InvalidInstant, parse_instant, temporal_wire


def read_probe_cache(path: Path | None, schema_version: int) -> dict[str, Any]:
    empty = {"schema_version": schema_version, "probed_at": None, "surfaces": {}}
    if path is None:
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != schema_version
    ):
        return empty
    try:
        raw = payload.get("probed_at")
        probed_at = parse_instant(raw) if raw is not None else None
    except InvalidInstant:
        return empty
    surfaces = payload.get("surfaces")
    return {
        "schema_version": schema_version,
        "probed_at": probed_at,
        "surfaces": dict(surfaces) if isinstance(surfaces, Mapping) else {},
    }


def write_probe_cache(path: Path | None, document: Mapping[str, Any]) -> None:
    if path is None:
        return
    raw = document.get("probed_at")
    document = {
        **document,
        "probed_at": parse_instant(raw) if raw is not None else None,
    }
    create_private_directory(path.parent)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(temporal_wire(document), sort_keys=True), encoding="utf-8"
    )
    temporary.chmod(0o600)
    temporary.replace(path)
