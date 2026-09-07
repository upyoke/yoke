"""Per-machine native model availability for the steering fleet report.

The seat placing work needs to know what each machine can actually select
before it names a model, and it needs that from the machines themselves
rather than from whatever catalog the running build was compiled with.

A surface is summarized rather than listed model by model: one machine
publishes over two hundred selectable tokens, and a report that printed them
all would bury every other fact in it. The exact tokens stay one read away in
``machine_native_models``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from yoke_contracts.session_control.native_models import (
    NATIVE_MODEL_SURFACES,
    available_models,
    sanitize_native_models,
)
from yoke_core.domain import db_backend


#: How many model tokens one surface row names before it says "and N more".
#: Enough to recognize the families on offer, few enough to stay one line.
NAMED_MODEL_SAMPLE = 6


@dataclass(frozen=True)
class MachineNativeModels:
    """One machine and surface's answer about what it can select."""

    machine_id: str
    #: The machine's registered name, which is what a person reading the
    #: report recognizes; a machine with no registry row falls back to its
    #: relay's reported host name.
    machine_name: str
    surface: str
    status: str
    reason: str | None
    source: str
    observed_at: str
    model_count: int
    sample_models: tuple[str, ...]

    @property
    def carries_models(self) -> bool:
        """Whether this row names models a launch could actually request."""
        return self.status in {"ok", "stale"} and self.model_count > 0


def _document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _projects(value: Any) -> set[int]:
    raw = value if isinstance(value, list) else None
    if raw is None:
        try:
            raw = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            return set()
    if not isinstance(raw, list):
        return set()
    found: set[int] = set()
    for item in raw:
        try:
            found.add(int(item))
        except (TypeError, ValueError):
            continue
    return found


def _cell(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]


def load_native_models(
    conn: Any,
    *,
    project_id: int,
    now: str,
    registered_names: Mapping[str, str] | None = None,
) -> tuple[MachineNativeModels, ...]:
    """Connected relays' latest availability for machines serving this project.

    ``registered_names`` lets a caller that already read the registry pass it
    in rather than paying for a second scan of the same rows.
    """
    from yoke_core.domain.machine_registry import machine_names

    names = machine_names(conn) if registered_names is None else registered_names
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT machine_id, hostname, project_checkouts, surface_native_models "
        f"FROM session_relays WHERE connected_until>={marker} "
        "ORDER BY hostname, machine_id",
        (now,),
    ).fetchall()
    found: list[MachineNativeModels] = []
    for row in rows:
        if int(project_id) not in _projects(_cell(row, "project_checkouts", 2)):
            continue
        readings = sanitize_native_models(
            _document(_cell(row, "surface_native_models", 3))
        )
        machine_id = str(_cell(row, "machine_id", 0))
        machine_name = (
            names.get(machine_id) or str(_cell(row, "hostname", 1)) or machine_id
        )
        for surface in NATIVE_MODEL_SURFACES:
            reading = readings.get(surface)
            if reading is None:
                continue
            models = available_models(reading)
            found.append(
                MachineNativeModels(
                    machine_id=machine_id,
                    machine_name=machine_name,
                    surface=surface,
                    status=str(reading.get("status") or "unknown"),
                    reason=reading.get("reason") or None,
                    source=str(reading.get("source") or ""),
                    observed_at=str(reading.get("observed_at") or ""),
                    model_count=len(models),
                    sample_models=models[:NAMED_MODEL_SAMPLE],
                )
            )
    return tuple(found)


def native_model_lines(rows: tuple[MachineNativeModels, ...]) -> list[str]:
    """Render one line per surface that has something to say.

    A surface Yoke has no adapter for is left out: repeating that absence on
    every machine block would cost more attention than it carries. A surface
    that should have answered and did not is printed, because that one is a
    condition somebody may need to fix.
    """
    printable = [row for row in rows if row.status != "unsupported"]
    if not printable:
        return []
    lines = ["  selectable models (observed natively):"]
    for row in sorted(printable, key=lambda item: item.surface):
        if not row.carries_models:
            lines.append(
                f"    {row.surface}: {row.status} — {row.reason or 'no reason recorded'}"
            )
            continue
        named = ", ".join(row.sample_models)
        remaining = row.model_count - len(row.sample_models)
        if remaining > 0:
            named = f"{named}, +{remaining} more"
        staleness = (
            "" if row.status == "ok" else f" (stale since {row.observed_at or 'unknown'})"
        )
        lines.append(f"    {row.surface}: {row.model_count}{staleness} — {named}")
    return lines


def fingerprint_material(
    rows: tuple[MachineNativeModels, ...]
) -> list[tuple[Any, ...]]:
    """What must change for the seat to be told availability changed.

    The sample alone would hide a new model that sorts past it, so the count
    and the status ride the fingerprint too.
    """
    return sorted(
        (
            row.machine_id,
            row.surface,
            row.status,
            row.reason,
            row.model_count,
            row.sample_models,
        )
        for row in rows
    )


__all__ = [
    "NAMED_MODEL_SAMPLE",
    "MachineNativeModels",
    "fingerprint_material",
    "load_native_models",
    "native_model_lines",
]
