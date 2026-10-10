"""One-time PostgreSQL storage conversion with explicit historical assumptions.

The governed history caller owns the frozen column roster, recovery point,
transaction, serving floor and receipts. This code is never an input parser:
future writers use the strict shared instant contract. This sibling is frozen
with the migration so installed runners need no candidate runtime imports.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from psycopg import sql

from yoke_contracts.schema_authority import refuse_without_serving_build_authority
from yoke_core.domain import administered_postgres


_OWNER_CREATION_REPAIRS = {
    ("items", "updated_at"),
    ("ouroboros_entries", "timestamp"),
}
_EPOCH_SECONDS = {
    ("frontend_attribution_redemptions", "expires_at"),
    ("frontend_event_rate_limits", "window_start"),
}


def _catalog(conn: Any) -> dict[tuple[str, str], tuple[str, bool, str | None]]:
    rows = conn.execute(
        "SELECT table_name,column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema = 'public'"
    ).fetchall()
    return {
        (str(row[0]), str(row[1])): (str(row[2]), row[3] == "YES", row[4])
        for row in rows
    }


def _text_instant(column: str) -> sql.Composed:
    return sql.SQL(
        "regexp_replace(NULLIF({}::text,''), "
        "'([.][0-9]{{6}})[0-9]+', E'\\\\1', 'g')::timestamptz"
    ).format(sql.Identifier(column))


def _expression(table: str, column: str, data_type: str) -> sql.Composable:
    name = sql.Identifier(column)
    if data_type in {"integer", "bigint"}:
        if (table, column) not in _EPOCH_SECONDS:
            raise RuntimeError(
                f"instant_epoch_unit_undeclared: {table}.{column}. Recovery: "
                "declare and verify its source unit before governing conversion."
            )
        # Integer seconds remain exact; no binary floating-point conversion.
        return sql.SQL(
            "TIMESTAMPTZ '1970-01-01 00:00:00+00' + ({}::text || ' seconds')::interval"
        ).format(name)
    if (table, column) not in _OWNER_CREATION_REPAIRS:
        return _text_instant(column)
    return sql.SQL(
        "CASE WHEN {value} IS NULL OR {value} = '' "
        "OR NOT pg_input_is_valid({value},'timestamp with time zone') "
        "THEN {creation} ELSE {instant} END"
    ).format(
        value=name,
        creation=_text_instant("created_at"),
        instant=_text_instant(column),
    )


def _admit_column(
    conn: Any, table: str, column: str, data_type: str, nullable: bool
) -> None:
    if data_type == "timestamp with time zone":
        return
    if data_type in {"integer", "bigint"}:
        _expression(table, column, data_type)
        return
    if data_type != "text":
        raise RuntimeError(
            f"instant_source_type_unsupported: {table}.{column} is {data_type}. "
            "Recovery: verify its declared instant storage before rehearsal."
        )
    value = sql.Identifier(column)
    if (table, column) in _OWNER_CREATION_REPAIRS:
        creation = sql.SQL("{}::text").format(sql.Identifier("created_at"))
        invalid = sql.SQL(
            "({value} IS NULL OR {value} = '' OR NOT "
            "pg_input_is_valid({value},'timestamp with time zone')) AND "
            "({creation} IS NULL OR {creation} = '' OR NOT "
            "pg_input_is_valid({creation},'timestamp with time zone'))"
        ).format(value=value, creation=creation)
    else:
        invalid = sql.SQL(
            "({value} <> '' AND NOT "
            "pg_input_is_valid({value},'timestamp with time zone'))"
        ).format(value=value)
        if not nullable:
            invalid = sql.SQL("{} OR {} IS NULL OR {} = ''").format(
                invalid, value, value
            )
    count = conn.execute(
        sql.SQL("SELECT COUNT(*) FROM {} WHERE {}").format(
            sql.Identifier(table), invalid
        )
    ).fetchone()[0]
    if count:
        raise RuntimeError(
            f"instant_historical_repair_unresolved: {table}.{column} has "
            f"{count} values without an approved usable owner fact. Recovery: "
            "inspect the restored-source census and author the deterministic "
            "owner repair before retrying governed rehearsal."
        )


def _detach_dependent_view(conn: Any, changing: set[tuple[str, str]]) -> bool:
    """Reconcile only the existing owned progress projection, without CASCADE."""
    if not changing:
        return False
    rows = conn.execute(
        "SELECT DISTINCT vn.nspname,v.relname,v.relkind,v.oid,"
        "t.relname,a.attname FROM pg_depend d "
        "JOIN pg_rewrite r ON d.classid='pg_rewrite'::regclass AND d.objid=r.oid "
        "JOIN pg_class v ON v.oid=r.ev_class "
        "JOIN pg_namespace vn ON vn.oid=v.relnamespace "
        "JOIN pg_class t ON d.refclassid='pg_class'::regclass AND t.oid=d.refobjid "
        "JOIN pg_namespace tn ON tn.oid=t.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid "
        "WHERE tn.nspname='public' AND v.oid<>t.oid"
    ).fetchall()
    affected = {tuple(row[:4]) for row in rows if (row[4], row[5]) in changing}
    if not affected:
        return False
    unknown = [
        f"{row[0]}.{row[1]}"
        for row in affected
        if row[:3] != ("public", "item_progress_view", "v")
    ]
    if not unknown:
        oid = next(iter(affected))[3]
        dependents = conn.execute(
            "SELECT DISTINCT n.nspname,v.relname FROM pg_depend d "
            "JOIN pg_rewrite r ON d.classid='pg_rewrite'::regclass AND d.objid=r.oid "
            "JOIN pg_class v ON v.oid=r.ev_class "
            "JOIN pg_namespace n ON n.oid=v.relnamespace "
            "WHERE d.refclassid='pg_class'::regclass AND d.refobjid=%s AND v.oid<>%s",
            (oid, oid),
        ).fetchall()
        unknown = [f"{row[0]}.{row[1]}" for row in dependents]
    if unknown:
        raise RuntimeError(
            "instant_dependent_view_unowned: "
            + ", ".join(sorted(unknown))
            + ". Recovery: declare the owner's transactional reconstruction before "
            "retrying governed rehearsal; no view was dropped."
        )
    custom = conn.execute(
        "SELECT relacl IS NOT NULL OR reloptions IS NOT NULL OR "
        "pg_get_userbyid(relowner)<>current_user OR "
        "obj_description(oid,'pg_class') IS NOT NULL FROM pg_class WHERE oid=%s",
        (next(iter(affected))[3],),
    ).fetchone()[0]
    if custom:
        raise RuntimeError(
            "instant_dependent_view_customized: public.item_progress_view has "
            "custom ownership, grants, options or commentary. Recovery: declare "
            "their exact transactional restoration before rehearsal; no view was dropped."
        )
    conn.execute("DROP VIEW item_progress_view")
    return True


def convert_stored_instants(conn: Any, columns: Iterable[tuple[str, str]]) -> None:
    """Convert a frozen history roster atomically in its caller's transaction.

    Historical date-only and offset-free values explicitly assume UTC.
    Optional blanks become NULL. Approved missing item updates and malformed
    Ouroboros observations use that same owner's valid creation stamp. One
    ALTER per table avoids rewriting a multi-instant table once per column.
    Native output is idempotent. UPDATE/DELETE guards are never suspended.
    """
    refuse_without_serving_build_authority(
        "converting governed stored instants",
        administering_env=administered_postgres.administering_target(connection=conn),
    )
    catalog = _catalog(conn)
    present = sorted(set(columns) & catalog.keys())
    conn.execute("SET LOCAL TIME ZONE 'UTC'")
    for table, column in present:
        data_type, nullable, _ = catalog[(table, column)]
        _admit_column(conn, table, column, data_type, nullable)
    by_table: dict[str, list[sql.Composable]] = defaultdict(list)
    defaults: list[sql.Composable] = []
    for table, column in present:
        data_type, _, default = catalog[(table, column)]
        if data_type == "timestamp with time zone":
            continue
        name = sql.Identifier(column)
        by_table[table].extend(
            (
                sql.SQL("ALTER COLUMN {} DROP DEFAULT").format(name),
                sql.SQL("ALTER COLUMN {} TYPE timestamptz USING {}").format(
                    name, _expression(table, column, data_type)
                ),
            )
        )
        if default and default not in {"''::text", "NULL::text"}:
            if data_type != "text":
                raise RuntimeError(
                    f"instant_default_unit_unresolved: {table}.{column}. "
                    "Recovery: author its native default before rehearsal."
                )
            defaults.append(
                sql.SQL(
                    "ALTER TABLE {} ALTER COLUMN {} SET DEFAULT ({})::timestamptz"
                ).format(sql.Identifier(table), name, sql.SQL(default))
            )
    restore_view = _detach_dependent_view(
        conn, {key for key in present if catalog[key][0] != "timestamp with time zone"}
    )
    for table, clauses in sorted(by_table.items()):
        conn.execute(
            sql.SQL("ALTER TABLE {} {}").format(
                sql.Identifier(table), sql.SQL(", ").join(clauses)
            )
        )
    for statement in defaults:
        conn.execute(statement)
    if restore_view:
        from yoke_core.domain.flow_init import create_or_replace_item_progress_view

        create_or_replace_item_progress_view(conn, commit=False)


def assert_native_stored_instants(
    conn: Any, columns: Iterable[tuple[str, str]]
) -> None:
    catalog = _catalog(conn)
    wrong = [
        f"{table}.{column}"
        for table, column in columns
        if (table, column) in catalog
        and catalog[(table, column)][0] != "timestamp with time zone"
    ]
    if wrong:
        raise AssertionError(
            "stored_instant_type_mismatch: "
            + ", ".join(wrong)
            + ". Recovery: rehearse the native-domain-instant history entry."
        )
