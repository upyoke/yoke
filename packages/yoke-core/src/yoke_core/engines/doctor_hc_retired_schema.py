"""HC-retired-schema-resurrection: retired-surface post-cutover drift.

Scans every project declared in ``runtime/api/domain/retired_schema_surfaces.yaml``
and verifies that each registered column or table is actually absent on
the model's schema target. A registered surface that is still present
is the precise failure mode governance targets: the cutover audit row is
completed, live code no longer references the surface, but the
target DB still exposes it because stale bootstrap / ambient
auto-init repaired it after the retirement landed.

The target is resolved by the migration-model database declaration:

* ``postgres`` — the authority is Yoke's connected control-plane DB.
  Presence is probed through the backend-aware ``schema_common`` catalog
  helpers (``information_schema`` on Postgres), i.e. the same connection
  doctor already holds. This is the live shape for Yoke's ``primary``
  model.
* ``sqlite_file`` — an external project SQLite file or archived import
  artifact. Presence is probed by opening that file directly. Yoke itself
  never uses this branch; ``project='yoke'`` with ``sqlite_file`` and root
  ``data/yoke.db`` paths fail closed as unresolvable.

Emits WARN with concrete drift details so the operator can:

  * identify the affected project, table, and optional column;
  * look up the migration module that retired the surface; and
  * re-run the retirement against the schema target (governed
    runner or exception pathway) to complete the cutover.

Registry load failures are surfaced as WARN with the parse error — a
malformed registry would silently disable the health check, which is
exactly the failure mode this HC exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import sqlite3

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
import yoke_core.engines.doctor_report as _base
from yoke_core.domain.retired_schema_registry import (
    RetiredSchemaRegistryError,
    RetiredSurface,
    load_registry,
)
from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_column_exists,
    _generic_sqlite_validation_table_exists,
)
from yoke_core.domain.sqlite_validation_boundary import (
    is_retired_root_yoke_db_path,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-retired-schema-resurrection"
_HC_DESC = "Retired schema surfaces still present on the schema target"


@dataclass(frozen=True)
class _Authority:
    """Resolved authoritative-DB binding for a (project, model)."""

    kind: str
    #: Absolute SQLite file path; populated only when ``kind == 'sqlite_file'``.
    sqlite_path: Optional[str] = None


def _row_value(row, key: str, index: int):
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return row[index]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_authority(
    conn, project: str, model: str
) -> Optional[_Authority]:
    """Resolve the authoritative-DB binding for (project, model).

    Reads ``project_capabilities.settings`` for the ``migration_model``
    capability and returns an :class:`_Authority` describing how to probe
    the surface:

    * ``kind == 'postgres'`` — probe the connected control-plane DB.
    * ``kind == 'sqlite_file'`` — probe the resolved external/archive SQLite
      file (path resolved relative to this machine's mapped checkout). Yoke
      control-plane SQLite and root ``data/yoke.db`` are refused.

    Returns ``None`` when any step fails or the kind is unsupported — the
    HC surfaces a per-surface skip with the reason rather than treating a
    resolution miss as drift.
    """
    try:
        p = _p(conn)
        project_id = resolve_project_id(conn, project)
        row = conn.execute(
            "SELECT settings FROM project_capabilities "
            f"WHERE project_id = {p} AND type = 'migration_model'",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        raw_settings = _row_value(row, "settings", 0)
        payload = json.loads(raw_settings) if raw_settings else {}
    except json.JSONDecodeError:
        return None
    except db_backend.database_error_types(conn):
        return None

    models = payload.get("models") or {}
    model_payload = models.get(model) or {}
    auth = model_payload.get("authoritative_db") or {}
    kind = auth.get("kind")

    if kind == "postgres":
        return _Authority(kind="postgres")

    if kind == "sqlite_file":
        if project == "yoke":
            return None
        location = auth.get("location") or {}
        rel = location.get("path")
        if not isinstance(rel, str) or not rel.strip():
            return None
        repo_path = checkout_for_project_id(project_id)
        if repo_path is None:
            return None
        try:
            sqlite_path = (Path(repo_path) / rel).resolve()
            if is_retired_root_yoke_db_path(sqlite_path):
                return None
            return _Authority(
                kind="sqlite_file",
                sqlite_path=str(sqlite_path),
            )
        except OSError:
            return None

    # Unknown / unsupported authoritative_db.kind.
    return None


def _control_plane_surface_present(conn, record: RetiredSurface) -> Optional[bool]:
    """Probe the connected control-plane DB for a retired surface.

    Uses the backend-aware ``schema_common`` catalog helpers, so this
    resolves against ``information_schema`` on Postgres, Yoke's live
    authority, and keeps any fixture/generic-file catalog handling inside
    the shared helper. Returns ``None`` only if the catalog probe itself
    raises.
    """
    try:
        if record.column is None:
            return _schema_table_exists(conn, record.table)
        return _schema_column_exists(conn, record.table, record.column)
    except Exception:
        return None


def _sqlite_file_column_present(
    db_path: str, table: str, column: str
) -> Optional[bool]:
    """Return column presence for a declared ``sqlite_file`` authority.

    ``None`` means the probe failed (DB unreadable, table missing, etc.)
    — surfaced separately so the HC can report it distinctly from drift.
    This helper is intentionally limited to genuine non-control-plane
    SQLite artifacts declared by an external project's migration model.
    """
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return None
    try:
        try:
            return _generic_sqlite_validation_column_exists(conn, table, column)
        except sqlite3.Error:
            return None
    finally:
        conn.close()


def _sqlite_file_table_present(db_path: str, table: str) -> Optional[bool]:
    """Return table presence for a declared ``sqlite_file`` authority.

    ``None`` means the probe failed (DB unreadable) — surfaced separately
    so the HC can report it distinctly from drift. This helper is
    intentionally limited to genuine non-control-plane SQLite artifacts
    declared by an external project's migration model.
    """
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return None
    try:
        try:
            return _generic_sqlite_validation_table_exists(conn, table)
        except sqlite3.Error:
            return None
    finally:
        conn.close()


def hc_retired_schema_resurrection(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Check every registered retired schema surface for resurrection."""
    try:
        surfaces = load_registry()
    except RetiredSchemaRegistryError as exc:
        rec.record(
            _HC_NAME,
            _HC_DESC,
            "WARN",
            f"- retired-schema registry is malformed: {exc}",
        )
        return

    if not surfaces:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    findings: List[str] = []
    skips: List[str] = []
    for record in surfaces:
        surface_label = (
            f"{record.project}/{record.table}.{record.column}"
            if record.column is not None
            else f"{record.project}/{record.table} (table-level)"
        )
        authority = _resolve_authority(conn, record.project, record.model)
        if authority is None:
            skips.append(
                f"- {surface_label}: "
                f"could not resolve schema target for model "
                f"'{record.model}' — skipped"
            )
            continue

        if authority.kind == "postgres":
            # The authority is Yoke's connected control-plane DB — the
            # same connection doctor already holds. Probe its catalog
            # directly rather than opening a separate file.
            present = _control_plane_surface_present(conn, record)
            if present is None:
                skips.append(
                    f"- {surface_label}: "
                    f"control-plane catalog probe failed — skipped"
                )
                continue
        else:  # sqlite_file
            db_path = authority.sqlite_path
            if db_path is None or not Path(db_path).exists():
                skips.append(
                    f"- {surface_label}: "
                    f"external SQLite target '{db_path}' not found — skipped"
                )
                continue
            if record.column is None:
                present = _sqlite_file_table_present(db_path, record.table)
            else:
                present = _sqlite_file_column_present(
                    db_path, record.table, record.column
                )
            if present is None:
                skips.append(
                    f"- {surface_label}: "
                    f"schema probe failed on {db_path} — skipped"
                )
                continue

        if present:
            findings.append(
                f"- {surface_label} still present "
                f"(retired by migration module '{record.module}')"
            )

    detail_lines: List[str] = []
    if findings:
        detail_lines.append(
            "Retired schema surfaces still exposed on schema target:"
        )
        detail_lines.extend(findings)
        detail_lines.append("")
        detail_lines.append(
            "Remediation: re-run the retiring module's apply against the "
            "schema target, either via the governed runner lifecycle hook "
            "or the exception pathway (``record_audit_fingerprint`` helper). "
            "Live-code references remain absent by design; the registry "
            "and doctor surface together detect the drift between the audit "
            "row and the DB shape."
        )
    if skips:
        if detail_lines:
            detail_lines.append("")
        detail_lines.append("Surfaces skipped (unresolvable):")
        detail_lines.extend(skips)

    if findings:
        rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(detail_lines))
    elif skips:
        rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(detail_lines))
    else:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
