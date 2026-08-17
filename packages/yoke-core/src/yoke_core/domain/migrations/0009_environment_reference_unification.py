"""Replace free-text deployment target labels with environment references.

Deployment flows and runs carried a ``target_env`` label that only
string-matched the environment registry, so ``"production"`` on a flow and
``"prod"`` on the environment named the same thing without ever joining, and
every consumer papered over the seam with its own alias map. The typed pair
``target_tier`` + ``target_environment_id`` (added by the boot converge)
replaces the label: ``persistent`` rows reference a registered environment
row, ``ephemeral`` rows deploy per-run preview substrate, and merge-only
flows carry neither.

This entry recodes what already exists: it resolves each legacy label to the
project's environment row (minting the row when a project has flows but no
registry — the registry is newer than the flows), copies the same resolution
onto historical runs, rewrites legacy long-form labels held in item
``deployed_to`` stamps, QA requirement targets and method configs, and fleet
preflight receipt events, then drops the label columns and installs the
tier/environment CHECK on databases born before the typed DDL.

Idempotent against its own output: resolution matches by environment id and
canonical name first, so a re-run (or a row the running code already
produced) folds onto the existing environment instead of minting a twin.
"""

from __future__ import annotations

import json
from typing import Any

#: The oldest artifact that may serve a database this entry has been applied
#: to. Derived rather than chosen: every build carrying this code is newer
#: than ``0.1.1+launch.225``, the published build at authoring time, because
#: that build still reads the dropped ``target_env`` columns. Build numbers
#: only increase, so the shipping build is at least ``launch.226``. Raising
#: it later needs its own evidence; lowering it re-admits a container that
#: reads dropped columns.
MINIMUM_SERVING_VERSION = "0.1.1+launch.226"

#: Canonical environment names for the long-form labels the label era used.
CANONICAL_ENVIRONMENT_NAMES = {"production": "prod", "staging": "stage"}

#: ``target_tier`` vocabulary (mirrors the flow-declaration contract; a
#: migration module stays frozen, so the values are pinned here).
TIER_PERSISTENT = "persistent"
TIER_EPHEMERAL = "ephemeral"

RECEIPT_EVENT_NAME = "FleetMigrationPreflightPassed"

_TABLES_WITH_TARGETS = ("deployment_flows", "deployment_runs")


def _canonical_name(label: str) -> str:
    return CANONICAL_ENVIRONMENT_NAMES.get(label.lower(), label.lower())


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(c[0]) for c in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _marker(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _now() -> str:
    from yoke_core.domain.db_helpers import iso8601_now

    return iso8601_now()


def _resolve_environment(conn: Any, project_id: int, label: str) -> str:
    """The environment id *label* names within *project_id*, minting if new.

    Matches by environment id first (a label-era flow could carry the row id
    itself), then by canonical name. A project with flows but no registered
    environment gets the row minted under its first site — the same shape
    operators register by hand — so the persistent tier's foreign key holds
    fleet-wide without waiting for manual registration.
    """
    p = _marker(conn)
    name = _canonical_name(label)
    rows = _rows(conn.execute(
        "SELECT e.id, e.name, s.id AS site_id FROM environments e "
        "JOIN sites s ON s.id = e.site "
        f"WHERE s.project_id = {p} ORDER BY e.created_at, e.id",
        (project_id,),
    ))
    for row in rows:
        if str(row["id"]) == label:
            return str(row["id"])
    for row in rows:
        if str(row["name"]).lower() == name:
            return str(row["id"])
    site_id = rows[0]["site_id"] if rows else _first_site(conn, project_id)
    environment_id = f"{site_id}-{name}"
    existing = _rows(conn.execute(
        f"SELECT id, site FROM environments WHERE id = {p}",
        (environment_id,),
    ))
    if existing:
        return str(existing[0]["id"])
    conn.execute(
        "INSERT INTO environments (id, site, name, created_at, settings) "
        f"VALUES ({p}, {p}, {p}, {p}, '{{}}')",
        (environment_id, site_id, name, _now()),
    )
    return environment_id


def _first_site(conn: Any, project_id: int) -> str:
    p = _marker(conn)
    rows = _rows(conn.execute(
        f"SELECT id FROM sites WHERE project_id = {p} "
        "ORDER BY created_at, id",
        (project_id,),
    ))
    if rows:
        return str(rows[0]["id"])
    slug_rows = _rows(conn.execute(
        f"SELECT slug FROM projects WHERE id = {p}", (project_id,),
    ))
    site_id = str(slug_rows[0]["slug"]) if slug_rows else f"project-{project_id}"
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at, settings) "
        f"VALUES ({p}, {p}, {p}, {p}, '{{}}')",
        (site_id, project_id, site_id, _now()),
    )
    return site_id


def _backfill_table(conn: Any, table: str) -> None:
    p = _marker(conn)
    rows = _rows(conn.execute(
        f"SELECT id, project_id, target_env FROM \"{table}\" "
        "WHERE target_env IS NOT NULL AND target_env <> '' "
        "AND target_tier IS NULL",
    ))
    for row in rows:
        label = str(row["target_env"]).strip()
        if label.lower() == TIER_EPHEMERAL:
            conn.execute(
                f"UPDATE \"{table}\" SET target_tier = {p} WHERE id = {p}",
                (TIER_EPHEMERAL, row["id"]),
            )
            continue
        environment_id = _resolve_environment(
            conn, int(row["project_id"]), label,
        )
        conn.execute(
            f"UPDATE \"{table}\" SET target_tier = {p}, "
            f"target_environment_id = {p} WHERE id = {p}",
            (TIER_PERSISTENT, environment_id, row["id"]),
        )


def _recode_label_column(conn: Any, table: str, column: str) -> None:
    p = _marker(conn)
    for legacy, canonical in CANONICAL_ENVIRONMENT_NAMES.items():
        conn.execute(
            f"UPDATE \"{table}\" SET \"{column}\" = {p} "
            f"WHERE \"{column}\" = {p}",
            (canonical, legacy),
        )


def _recode_environment_values(node: Any) -> bool:
    """Rewrite long-form environment labels held under environment keys."""
    changed = False
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key in {"active_env", "target_env", "environment"}
                and isinstance(value, str)
                and value.lower() in CANONICAL_ENVIRONMENT_NAMES
            ):
                node[key] = CANONICAL_ENVIRONMENT_NAMES[value.lower()]
                changed = True
            else:
                changed = _recode_environment_values(value) or changed
    elif isinstance(node, list):
        for child in node:
            changed = _recode_environment_values(child) or changed
    return changed


def _recode_json_column(conn: Any, table: str, key: str, column: str) -> None:
    p = _marker(conn)
    rows = _rows(conn.execute(
        f"SELECT \"{key}\" AS row_key, \"{column}\" AS doc FROM \"{table}\" "
        f"WHERE \"{column}\" LIKE '%production%' "
        f"OR \"{column}\" LIKE '%staging%'",
    ))
    for row in rows:
        try:
            doc = json.loads(row["doc"])
        except (TypeError, ValueError):
            continue
        if _recode_environment_values(doc):
            conn.execute(
                f"UPDATE \"{table}\" SET \"{column}\" = {p} "
                f"WHERE \"{key}\" = {p}",
                (json.dumps(doc, separators=(",", ":")), row["row_key"]),
            )


def _recode_receipt_events(conn: Any) -> None:
    p = _marker(conn)
    rows = _rows(conn.execute(
        f"SELECT id, envelope FROM events WHERE event_name = {p}",
        (RECEIPT_EVENT_NAME,),
    ))
    for row in rows:
        try:
            envelope = json.loads(row["envelope"])
        except (TypeError, ValueError):
            continue
        if _recode_environment_values(envelope):
            conn.execute(
                f"UPDATE events SET envelope = {p} WHERE id = {p}",
                (json.dumps(envelope, separators=(",", ":")), row["id"]),
            )


def _install_target_checks(conn: Any, table: str) -> None:
    """Install the tier vocabulary and tier/environment pairing CHECKs.

    Postgres only: databases born from the typed DDL carry the constraints
    inline, and the SQLite validation surface cannot ALTER TABLE ADD
    CONSTRAINT — its fresh fixtures are created from the typed DDL anyway.
    """
    from yoke_core.domain import db_backend

    if not db_backend.connection_is_postgres(conn):
        return
    constraints = {
        f"{table}_target_tier_vocabulary": (
            "(target_tier IS NULL OR "
            "target_tier IN ('persistent','ephemeral'))"
        ),
        f"{table}_target_tier_environment": (
            "((target_tier IS NOT NULL AND target_tier = 'persistent') "
            "= (target_environment_id IS NOT NULL))"
        ),
    }
    for name, predicate in constraints.items():
        present = _rows(conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s", (name,),
        ))
        if not present:
            conn.execute(
                f"ALTER TABLE \"{table}\" ADD CONSTRAINT \"{name}\" "
                f"CHECK {predicate}"
            )


def apply(conn: Any) -> None:
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    for table in _TABLES_WITH_TARGETS:
        if not _table_exists(conn, table):
            continue
        if _column_exists(conn, table, "target_env"):
            _backfill_table(conn, table)
            conn.execute(f"ALTER TABLE \"{table}\" DROP COLUMN target_env")
        _install_target_checks(conn, table)
    if _table_exists(conn, "items"):
        _recode_label_column(conn, "items", "deployed_to")
    if _table_exists(conn, "qa_requirements"):
        _recode_label_column(conn, "qa_requirements", "target_env")
        _recode_json_column(conn, "qa_requirements", "id", "method_config")
    if _table_exists(conn, "events"):
        _recode_receipt_events(conn)


def invariants(conn: Any) -> None:
    """Prove the label era ended and every persistent target resolves."""
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    for table in _TABLES_WITH_TARGETS:
        if not _table_exists(conn, table):
            continue
        if _column_exists(conn, table, "target_env"):
            raise AssertionError(
                f"{table}.target_env is retired but still present"
            )
        orphans = _rows(conn.execute(
            f"SELECT id FROM \"{table}\" "
            "WHERE (target_tier = 'persistent') "
            "AND target_environment_id IS NULL",
        ))
        if orphans:
            raise AssertionError(
                f"{table} persistent rows without an environment reference: "
                + ", ".join(str(r["id"]) for r in orphans)
            )
        if _table_exists(conn, "environments"):
            dangling = _rows(conn.execute(
                f"SELECT t.id FROM \"{table}\" t "
                "LEFT JOIN environments e ON e.id = t.target_environment_id "
                "WHERE t.target_environment_id IS NOT NULL AND e.id IS NULL",
            ))
            if dangling:
                raise AssertionError(
                    f"{table} rows referencing absent environments: "
                    + ", ".join(str(r["id"]) for r in dangling)
                )


__all__ = [
    "CANONICAL_ENVIRONMENT_NAMES",
    "MINIMUM_SERVING_VERSION",
    "RECEIPT_EVENT_NAME",
    "apply",
    "invariants",
]
