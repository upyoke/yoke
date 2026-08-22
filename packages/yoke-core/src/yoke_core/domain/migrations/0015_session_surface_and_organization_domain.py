"""Converge session surfaces and organization identity-domain policy."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
import uuid

from yoke_contracts.executor_labels import (
    CANONICAL_HARNESS_IDS,
    KNOWN_SURFACE_LABELS,
)
from yoke_contracts.organization_contract.fleet_keys import merge_fleet_settings
from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)
from yoke_core.domain.session_control_schema import (
    SESSION_CONTROL_TABLES,
    create_session_control_tables,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
SESSION_TABLE = "harness_sessions"
ORGANIZATION_TABLE = "organizations"
RENAMED_COLUMNS = (
    (SESSION_TABLE, "executor_display_name", "executor_surface"),
    (ORGANIZATION_TABLE, "auto_join_domain", "domain"),
)
AUTO_JOIN_SETTING = "membership.auto_join_domain_verified"
SURFACE_AUDIT_EVENT = "HarnessSessionSurfaceNormalized"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rename_or_converge(
    conn: Any,
    table: str,
    retired: str,
    current: str,
) -> None:
    if not _table_exists(conn, table) or not _column_exists(conn, table, retired):
        return
    if _column_exists(conn, table, current):
        conn.execute(
            f'UPDATE "{table}" SET "{current}" = "{retired}" '
            f'WHERE "{retired}" IS NOT NULL'
        )
        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{retired}"')
        return
    conn.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{retired}" TO "{current}"')


def _normalize_executors(conn: Any) -> None:
    if not _table_exists(conn, SESSION_TABLE):
        return
    marker = _p(conn)
    conn.execute(
        f"UPDATE {SESSION_TABLE} SET executor={marker} WHERE executor={marker}",
        ("claude-code", "claude"),
    )
    allowed = sorted(CANONICAL_HARNESS_IDS)
    placeholders = ", ".join([marker] * len(allowed))
    rows = conn.execute(
        f"SELECT executor, COUNT(*) FROM {SESSION_TABLE} "
        f"WHERE executor NOT IN ({placeholders}) GROUP BY executor ORDER BY executor",
        tuple(allowed),
    ).fetchall()
    if rows:
        detail = ", ".join(f"{row[0]!r} ({int(row[1])})" for row in rows)
        raise AssertionError(f"unknown harness session executor families: {detail}")


def _event_columns_available(conn: Any) -> bool:
    required = (
        "event_id",
        "source_type",
        "session_id",
        "severity",
        "event_kind",
        "event_type",
        "event_name",
        "service",
        "envelope",
        "created_at",
    )
    return _table_exists(conn, "events") and all(
        _column_exists(conn, "events", column) for column in required
    )


def _record_surface_audit(conn: Any, value: str, count: int) -> None:
    if not _event_columns_available(conn):
        return
    marker = _p(conn)
    event_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"yoke:{SURFACE_AUDIT_EVENT}:{value}")
    )
    envelope = json.dumps(
        {"discarded_surface": value, "row_count": count},
        sort_keys=True,
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    placeholders = ", ".join([marker] * 10)
    conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity, "
        "event_kind, event_type, event_name, service, envelope, created_at) "
        f"VALUES ({placeholders}) ON CONFLICT(event_id) DO NOTHING",
        (
            event_id,
            "system",
            "migration:session-surface",
            "WARN",
            "migration",
            "normalization",
            SURFACE_AUDIT_EVENT,
            "core",
            envelope,
            now,
        ),
    )


def _normalize_surfaces(conn: Any) -> None:
    if not _column_exists(conn, SESSION_TABLE, "executor_surface"):
        return
    marker = _p(conn)
    allowed = sorted(KNOWN_SURFACE_LABELS)
    placeholders = ", ".join([marker] * len(allowed))
    rows = conn.execute(
        f"SELECT executor_surface, COUNT(*) FROM {SESSION_TABLE} "
        "WHERE executor_surface IS NOT NULL "
        f"AND executor_surface NOT IN ({placeholders}) "
        "GROUP BY executor_surface ORDER BY executor_surface",
        tuple(allowed),
    ).fetchall()
    for row in rows:
        value, count = str(row[0]), int(row[1])
        _record_surface_audit(conn, value, count)
        conn.execute(
            f"UPDATE {SESSION_TABLE} SET executor_surface=NULL "
            f"WHERE executor_surface={marker}",
            (value,),
        )


def _enforce_surface_check(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    rows = conn.execute(
        "SELECT con.conname FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c' "
        "AND pg_get_constraintdef(con.oid) ILIKE '%%executor_surface%%'",
        (SESSION_TABLE,),
    ).fetchall()
    for row in rows:
        name = str(row[0]).replace('"', '""')
        conn.execute(f'ALTER TABLE "{SESSION_TABLE}" DROP CONSTRAINT "{name}"')
    values = ", ".join(f"'{value}'" for value in sorted(KNOWN_SURFACE_LABELS))
    conn.execute(
        f"ALTER TABLE {SESSION_TABLE} ADD CONSTRAINT "
        "harness_sessions_executor_surface_check CHECK "
        f"(executor_surface IS NULL OR executor_surface IN ({values}))"
    )


def _enforce_executor_check(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    rows = conn.execute(
        "SELECT con.conname FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c' "
        "AND pg_get_constraintdef(con.oid) ILIKE '%%executor%%' "
        "AND pg_get_constraintdef(con.oid) NOT ILIKE '%%executor_surface%%'",
        (SESSION_TABLE,),
    ).fetchall()
    for row in rows:
        name = str(row[0]).replace('"', '""')
        conn.execute(f'ALTER TABLE "{SESSION_TABLE}" DROP CONSTRAINT "{name}"')
    values = ", ".join(f"'{value}'" for value in sorted(CANONICAL_HARNESS_IDS))
    conn.execute(
        f"ALTER TABLE {SESSION_TABLE} ADD CONSTRAINT "
        "harness_sessions_executor_check CHECK "
        f"(executor IN ({values}))"
    )


def _parse_settings(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError) as exc:
        raise AssertionError("organization settings must contain JSON objects") from exc
    if not isinstance(parsed, dict):
        raise AssertionError("organization settings must contain JSON objects")
    return parsed


def _migrate_organization_policy(conn: Any) -> None:
    if not _table_exists(conn, ORGANIZATION_TABLE):
        return
    had_retired = _column_exists(conn, ORGANIZATION_TABLE, "auto_join_domain")
    _add_column_if_not_exists(conn, ORGANIZATION_TABLE, "domain", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(
        conn,
        ORGANIZATION_TABLE,
        "settings",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    if had_retired:
        marker = _p(conn)
        rows = conn.execute(
            "SELECT id, auto_join_domain, settings FROM organizations "
            "WHERE auto_join_domain IS NOT NULL"
        ).fetchall()
        for row in rows:
            settings, _ = merge_fleet_settings(
                _parse_settings(row[2]),
                {"membership": {"auto_join_domain_verified": True}},
            )
            conn.execute(
                f"UPDATE organizations SET domain={marker}, settings={marker} "
                f"WHERE id={marker}",
                (row[1], json.dumps(settings, sort_keys=True), row[0]),
            )
    _rename_or_converge(
        conn,
        ORGANIZATION_TABLE,
        "auto_join_domain",
        "domain",
    )


def apply(conn: Any) -> None:
    if _table_exists(conn, SESSION_TABLE):
        _add_column_if_not_exists(
            conn,
            SESSION_TABLE,
            "executor_surface",
            "TEXT DEFAULT NULL",
        )
        _add_column_if_not_exists(
            conn,
            SESSION_TABLE,
            "executor_version",
            "TEXT DEFAULT NULL",
        )
        _add_column_if_not_exists(
            conn,
            SESSION_TABLE,
            "machine_id",
            "TEXT DEFAULT NULL",
        )
        _rename_or_converge(
            conn,
            SESSION_TABLE,
            "executor_display_name",
            "executor_surface",
        )
        _normalize_executors(conn)
        _enforce_executor_check(conn)
        _normalize_surfaces(conn)
        if _column_exists(conn, SESSION_TABLE, "capabilities"):
            conn.execute(f"ALTER TABLE {SESSION_TABLE} DROP COLUMN capabilities")
        _enforce_surface_check(conn)
    _migrate_organization_policy(conn)
    create_session_control_tables(conn)


def invariants(conn: Any) -> None:
    for table, retired, current in RENAMED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        if _column_exists(conn, table, retired):
            raise AssertionError(f"{table}.{retired} is retired")
        if not _column_exists(conn, table, current):
            raise AssertionError(f"{table}.{current} is required")
    if _table_exists(conn, SESSION_TABLE):
        for column in ("executor_version", "machine_id"):
            if not _column_exists(conn, SESSION_TABLE, column):
                raise AssertionError(f"{SESSION_TABLE}.{column} is required")
        if _column_exists(conn, SESSION_TABLE, "capabilities"):
            raise AssertionError("per-session capabilities are retired")
        marker = _p(conn)
        executors = sorted(CANONICAL_HARNESS_IDS)
        executor_placeholders = ", ".join([marker] * len(executors))
        unknown_executors = conn.execute(
            f"SELECT COUNT(*) FROM {SESSION_TABLE} "
            f"WHERE executor NOT IN ({executor_placeholders})",
            tuple(executors),
        ).fetchone()[0]
        if unknown_executors:
            raise AssertionError("harness session executor families are not canonical")
        allowed = sorted(KNOWN_SURFACE_LABELS)
        placeholders = ", ".join([marker] * len(allowed))
        invalid = conn.execute(
            f"SELECT COUNT(*) FROM {SESSION_TABLE} "
            "WHERE executor_surface IS NOT NULL "
            f"AND executor_surface NOT IN ({placeholders})",
            tuple(allowed),
        ).fetchone()[0]
        if invalid:
            raise AssertionError("harness session surfaces are not canonical")
    if _table_exists(conn, ORGANIZATION_TABLE) and not _column_exists(
        conn,
        ORGANIZATION_TABLE,
        "settings",
    ):
        raise AssertionError("organizations.settings is required")
    for table in SESSION_CONTROL_TABLES:
        if not _table_exists(conn, table):
            raise AssertionError(f"{table} is required")


__all__ = [
    "AUTO_JOIN_SETTING",
    "MINIMUM_SERVING_VERSION",
    "RENAMED_COLUMNS",
    "SESSION_TABLE",
    "SURFACE_AUDIT_EVENT",
    "apply",
    "invariants",
]
