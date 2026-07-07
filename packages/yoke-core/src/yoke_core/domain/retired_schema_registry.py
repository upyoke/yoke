"""Loader + query helpers for the retired-schema surface registry.

The declarative source is the runtime-owned
``runtime/api/domain/retired_schema_surfaces.yaml`` asset. Every entry names a
retired schema surface (column on a
table, or a table on its own) that must not be re-created by any
ambient init or idempotent bootstrap path.

This module exposes:

* :func:`load_registry` — read + parse the YAML file, returning the
  full list of :class:`RetiredSurface` records.  Cached per repo root
  so repeated consults within a process do not re-read the file.
* :func:`is_retired_column` — cheap predicate for init/bootstrap
  call sites.  ``True`` when the (project, table, column) tuple is
  present in the registry.
* :func:`lookup_module` — for a retired column, return the migration
  module identifier that retired it (used by the gate error message).
* :func:`list_retired_columns_for_table` — enumerate retired columns
  on a table; consumed by the doctor health check.

The registry is the **only** live source allowed to name retired
columns by their literal identifier.  All other live code paths
consult the registry rather than hard-coding names.

Owner: ``yoke_core.domain`` (governed DB mutation substrate).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


_REGISTRY_REL_PATH = "runtime/api/domain/retired_schema_surfaces.yaml"


class RetiredSchemaRegistryError(Exception):
    """Raised when the registry file is malformed."""


@dataclass(frozen=True)
class RetiredSurface:
    """One retired schema surface entry."""

    module: str
    project: str
    model: str
    table: str
    column: Optional[str]
    decision_record: Optional[str]


_REGISTRY_CACHE: Dict[str, List[RetiredSurface]] = {}
_CACHE_LOCK = threading.Lock()


def _resolve_registry_path(repo_root: Optional[Path]) -> Path:
    """Return the absolute path to the registry file."""
    if repo_root is not None:
        return Path(repo_root).resolve() / _REGISTRY_REL_PATH
    return Path(__file__).resolve().with_name("retired_schema_surfaces.yaml")


def _parse_payload(payload: object, source: str) -> List[RetiredSurface]:
    if payload is None:
        return []
    if not isinstance(payload, dict):
        raise RetiredSchemaRegistryError(
            f"{source}: expected top-level mapping, got {type(payload).__name__}"
        )
    surfaces_raw = payload.get("surfaces")
    if surfaces_raw is None:
        return []
    if not isinstance(surfaces_raw, list):
        raise RetiredSchemaRegistryError(
            f"{source}: 'surfaces' must be a list"
        )

    out: List[RetiredSurface] = []
    for idx, entry in enumerate(surfaces_raw):
        if not isinstance(entry, dict):
            raise RetiredSchemaRegistryError(
                f"{source}: surfaces[{idx}] must be a mapping"
            )
        for required in ("module", "project", "model", "table"):
            val = entry.get(required)
            if not isinstance(val, str) or not val.strip():
                raise RetiredSchemaRegistryError(
                    f"{source}: surfaces[{idx}] is missing required "
                    f"string field '{required}'"
                )
        column_raw = entry.get("column")
        column: Optional[str]
        if column_raw is None:
            column = None
        elif isinstance(column_raw, str) and column_raw.strip():
            column = column_raw
        else:
            raise RetiredSchemaRegistryError(
                f"{source}: surfaces[{idx}].column must be a non-empty "
                "string or omitted for table-level retirement"
            )
        record_raw = entry.get("decision_record")
        record: Optional[str]
        if record_raw is None:
            record = None
        elif isinstance(record_raw, str) and record_raw.strip():
            record = record_raw
        else:
            raise RetiredSchemaRegistryError(
                f"{source}: surfaces[{idx}].decision_record must be a "
                "non-empty string or omitted"
            )
        out.append(
            RetiredSurface(
                module=entry["module"],
                project=entry["project"],
                model=entry["model"],
                table=entry["table"],
                column=column,
                decision_record=record,
            )
        )
    return out


def load_registry(
    repo_root: Optional[Path] = None, *, force_reload: bool = False
) -> List[RetiredSurface]:
    """Load the retired-schema registry.

    Results are cached per resolved path so repeated consults inside a
    process (doctor runs, test loops, init hot paths) don't re-open the
    YAML file.  Tests that mutate the registry on disk can pass
    ``force_reload=True`` to bypass the cache.
    """
    path = _resolve_registry_path(repo_root)
    key = str(path)
    with _CACHE_LOCK:
        if not force_reload and key in _REGISTRY_CACHE:
            return _REGISTRY_CACHE[key]
        if not path.is_file():
            _REGISTRY_CACHE[key] = []
            return _REGISTRY_CACHE[key]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RetiredSchemaRegistryError(
                f"{path}: could not read registry file: {exc}"
            ) from exc
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RetiredSchemaRegistryError(
                f"{path}: invalid YAML: {exc}"
            ) from exc
        records = _parse_payload(payload, source=str(path))
        _REGISTRY_CACHE[key] = records
        return records


def clear_cache() -> None:
    """Drop the in-process cache.  Tests only."""
    with _CACHE_LOCK:
        _REGISTRY_CACHE.clear()


def is_retired_column(
    project: str,
    table: str,
    column: str,
    *,
    repo_root: Optional[Path] = None,
) -> bool:
    """Return ``True`` when the (project, table, column) is retired."""
    for record in load_registry(repo_root):
        if (
            record.project == project
            and record.table == table
            and record.column == column
        ):
            return True
    return False


def lookup_module(
    project: str,
    table: str,
    column: str,
    *,
    repo_root: Optional[Path] = None,
) -> Optional[str]:
    """Return the migration module that retired this column, or ``None``."""
    for record in load_registry(repo_root):
        if (
            record.project == project
            and record.table == table
            and record.column == column
        ):
            return record.module
    return None


def list_retired_columns_for_table(
    project: str,
    table: str,
    *,
    repo_root: Optional[Path] = None,
) -> List[RetiredSurface]:
    """Return all retired surfaces for a given (project, table)."""
    return [
        record
        for record in load_registry(repo_root)
        if record.project == project
        and record.table == table
        and record.column is not None
    ]


def list_all_retired_columns(
    *, repo_root: Optional[Path] = None
) -> List[RetiredSurface]:
    """Return every registered (project, table, column) entry."""
    return [
        record
        for record in load_registry(repo_root)
        if record.column is not None
    ]


def retired_column_key(record: RetiredSurface) -> Tuple[str, str, str]:
    """Stable hashable key for a column-level retirement."""
    assert record.column is not None
    return (record.project, record.table, record.column)


def guard_add_column(
    project: str,
    table: str,
    column: str,
    *,
    caller: str,
    repo_root: Optional[Path] = None,
) -> bool:
    """Return ``True`` when ``ALTER TABLE ... ADD COLUMN`` is allowed.

    Consults the retired-schema registry and, when the (project, table,
    column) tuple matches a retired surface, emits a WARN
    :event:`RetiredSchemaResurrectionAttempt` structured event and
    returns ``False``.  Callers MUST skip the ``ADD COLUMN`` when this
    helper returns ``False``.

    The helper never raises on registry errors — a malformed registry
    degrades to "allow" so init/bootstrap does not block recovery.  A
    separate health check flags the malformed registry as a WARN.

    :param caller: short module path of the caller (e.g.
        ``yoke_core.domain.projects_restart``) for event attribution.
    """
    try:
        module = lookup_module(project, table, column, repo_root=repo_root)
    except RetiredSchemaRegistryError:
        return True

    if module is None:
        return True

    _emit_resurrection_warn(
        project=project,
        table=table,
        column=column,
        module=module,
        caller=caller,
    )
    return False


def _emit_resurrection_warn(
    *, project: str, table: str, column: str, module: str, caller: str
) -> None:
    """Emit a WARN ``RetiredSchemaResurrectionAttempt`` event.

    Failures are swallowed — event emission must not break init /
    bootstrap.  The accompanying registry guard still returns ``False``
    regardless of whether the event landed.
    """
    try:  # pragma: no cover - belt-and-braces isolation
        import json
        import os
        import uuid

        from yoke_core.domain import events_writes

        envelope = json.dumps(
            {
                "project": project,
                "table": table,
                "column": column,
                "retiring_module": module,
                "caller": caller,
                "guidance": (
                    "ADD COLUMN skipped because the surface is registered as "
                    "retired in runtime/api/domain/retired_schema_surfaces.yaml. "
                    "Investigate the caller if the surface should be "
                    "restored via an explicit governed mutation."
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        session_id = os.environ.get(
            "CLAUDE_SESSION_ID"
        ) or os.environ.get("YOKE_SESSION_ID") or "system"
        events_writes.cmd_insert(
            event_id=f"retired-schema-{uuid.uuid4().hex}",
            source_type="system",
            session_id=session_id,
            severity="WARN",
            event_kind="system",
            event_type="schema_guard",
            event_name="RetiredSchemaResurrectionAttempt",
            service=caller,
            project=project,
            envelope=envelope,
            skip_severity=True,
        )
    except Exception:  # noqa: BLE001 - best effort
        return


__all__ = [
    "RetiredSurface",
    "RetiredSchemaRegistryError",
    "load_registry",
    "clear_cache",
    "is_retired_column",
    "lookup_module",
    "list_retired_columns_for_table",
    "list_all_retired_columns",
    "retired_column_key",
    "guard_add_column",
]
