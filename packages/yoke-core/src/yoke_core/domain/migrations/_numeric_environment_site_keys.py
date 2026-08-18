"""Frozen helpers for the numeric site/environment key cutover."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.migrations._numeric_environment_site_json import (
    recode_stored_references,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


DEPENDENT_TABLES = (
    "deployment_flows",
    "deployment_runs",
    "qa_plans",
)
LEGACY_ENVIRONMENTS = "environments_text_keys"
LEGACY_SITES = "sites_text_keys"

_NEW_REGISTRY_SQL = """
CREATE TABLE sites (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    settings TEXT DEFAULT '{}',
    UNIQUE(id, project_id),
    UNIQUE(project_id, name)
);
CREATE TABLE environments (
    id INTEGER PRIMARY KEY,
    site INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    url TEXT,
    deploy_method TEXT,
    deploy_command TEXT,
    health_check_url TEXT,
    config_notes TEXT,
    last_deployed_at TEXT,
    created_at TEXT NOT NULL,
    settings TEXT DEFAULT '{}',
    UNIQUE(project_id, name),
    FOREIGN KEY(site, project_id) REFERENCES sites(id, project_id)
);
"""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row, strict=True))
        for row in cursor.fetchall()
    ]


def _one(cursor: Any) -> Any:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("numeric key insert did not return an id")
    return row["id"] if hasattr(row, "keys") else row[0]


def registry_is_numeric(conn: Any) -> bool:
    if not _table_exists(conn, "sites") or not _table_exists(conn, "environments"):
        return False
    if not _column_exists(conn, "environments", "project_id"):
        return False
    if db_backend.connection_is_postgres(conn):
        p = _p(conn)
        rows = _rows(conn.execute(
            "SELECT table_name, data_type FROM information_schema.columns "
            "WHERE table_schema=current_schema() "
            f"AND table_name IN ({p},{p}) AND column_name='id'",
            ("sites", "environments"),
        ))
        return len(rows) == 2 and all(row["data_type"] == "integer" for row in rows)
    for table in ("sites", "environments"):
        rows = _rows(conn.execute(f"PRAGMA table_info({table})"))
        id_row = next((row for row in rows if row["name"] == "id"), None)
        if id_row is None or str(id_row["type"]).upper() != "INTEGER":
            return False
    return True


def _drop_target_constraints(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    for table in DEPENDENT_TABLES:
        if not _table_exists(conn, table):
            continue
        constraints = _rows(conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid=to_regclass(%s) "
            "AND (pg_get_constraintdef(oid) LIKE '%%target_environment_id%%' "
            "OR conname=%s)",
            (table, f"{table}_target_tier_vocabulary"),
        ))
        for row in constraints:
            conn.execute(
                f'ALTER TABLE "{table}" DROP CONSTRAINT "{row["conname"]}"'
            )


def _drop_registry_constraints(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    for table in ("environments", "sites"):
        constraints = _rows(conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid=to_regclass(%s) AND contype IN ('p','u','f')",
            (table,),
        ))
        for row in constraints:
            conn.execute(
                f'ALTER TABLE "{table}" DROP CONSTRAINT "{row["conname"]}"'
            )


def _copy_sites(conn: Any) -> tuple[dict[str, int], dict[str, str]]:
    legacy = _rows(conn.execute(
        f"SELECT id,project_id,name,description,created_at,settings "
        f"FROM {LEGACY_SITES} ORDER BY created_at,id"
    ))
    site_ids: dict[str, int] = {}
    site_names: dict[str, str] = {}
    p = _p(conn)
    for row in legacy:
        new_id = int(_one(conn.execute(
            "INSERT INTO sites(project_id,name,description,created_at,settings) "
            f"VALUES ({p},{p},{p},{p},{p}) RETURNING id",
            (
                int(row["project_id"]), row["name"], row["description"],
                row["created_at"], row["settings"],
            ),
        )))
        site_ids[str(row["id"])] = new_id
        site_names[str(row["id"])] = str(row["name"])
    return site_ids, site_names


def _copy_environments(
    conn: Any,
    site_ids: Mapping[str, int],
) -> tuple[dict[str, int], dict[str, str]]:
    legacy = _rows(conn.execute(
        f"SELECT e.*,s.project_id FROM {LEGACY_ENVIRONMENTS} e "
        f"JOIN {LEGACY_SITES} s ON s.id=e.site ORDER BY e.created_at,e.id"
    ))
    env_ids: dict[str, int] = {}
    env_names: dict[str, str] = {}
    p = _p(conn)
    columns = (
        "site,project_id,name,url,deploy_method,deploy_command,health_check_url,"
        "config_notes,last_deployed_at,created_at,settings"
    )
    values = ",".join([p] * 11)
    for row in legacy:
        old_id = str(row["id"])
        new_id = int(_one(conn.execute(
            f"INSERT INTO environments({columns}) VALUES ({values}) RETURNING id",
            (
                site_ids[str(row["site"])], int(row["project_id"]), row["name"],
                row["url"], row["deploy_method"], row["deploy_command"],
                row["health_check_url"], row["config_notes"],
                row["last_deployed_at"], row["created_at"], row["settings"],
            ),
        )))
        env_ids[old_id] = new_id
        env_names[old_id] = str(row["name"])
    return env_ids, env_names


def _rewrite_dependent_columns(conn: Any, env_ids: Mapping[str, int]) -> None:
    if not db_backend.connection_is_postgres(conn):
        for table in DEPENDENT_TABLES:
            if _table_exists(conn, table) and _column_exists(
                conn, table, "target_environment_id"
            ):
                _rewrite_sqlite_dependent(conn, table, env_ids)
        return
    p = _p(conn)
    for table in DEPENDENT_TABLES:
        if not _table_exists(conn, table) or not _column_exists(
            conn, table, "target_environment_id"
        ):
            continue
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN target_environment_key INTEGER')
        for old_id, new_id in env_ids.items():
            conn.execute(
                f'UPDATE "{table}" SET target_environment_key={p} '
                f'WHERE target_environment_id={p}',
                (new_id, old_id),
            )
        missing = _rows(conn.execute(
            f'SELECT target_environment_id FROM "{table}" '
            "WHERE target_environment_id IS NOT NULL "
            "AND target_environment_key IS NULL LIMIT 10"
        ))
        if missing:
            raise AssertionError(
                f"{table} carries unknown environment references: "
                + ", ".join(str(row["target_environment_id"]) for row in missing)
            )
        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN target_environment_id')
        conn.execute(
            f'ALTER TABLE "{table}" RENAME COLUMN '
            "target_environment_key TO target_environment_id"
        )


def _rewrite_sqlite_dependent(
    conn: Any,
    table: str,
    env_ids: Mapping[str, int],
) -> None:
    """Rebuild one SQLite table because DROP COLUMN cannot shed its FK/check."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"SQLite schema text is unavailable for {table}")
    temp = f"numeric_{table}"
    create_sql = re.sub(
        rf"^CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[\"']?{re.escape(table)}[\"']?",
        f'CREATE TABLE "{temp}"',
        str(row[0]),
        count=1,
        flags=re.IGNORECASE,
    )
    create_sql = re.sub(
        r"\btarget_environment_id\s+TEXT\b",
        "target_environment_id INTEGER",
        create_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    create_sql = re.sub(
        r"REFERENCES\s+[\"']?environments_text_keys[\"']?",
        "REFERENCES environments",
        create_sql,
        flags=re.IGNORECASE,
    )
    indexes = [
        index[0]
        for index in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('index','trigger') "
            "AND tbl_name=? AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    columns = [
        str(column["name"] if hasattr(column, "keys") else column[1])
        for column in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    ]
    p = _p(conn)
    clauses: list[str] = []
    parameters: list[Any] = []
    for old_id, new_id in env_ids.items():
        clauses.append(f"WHEN {p} THEN {p}")
        parameters.extend((old_id, new_id))
    target = "CASE target_environment_id " + " ".join(clauses) + " ELSE NULL END"
    projections = [target if column == "target_environment_id" else f'"{column}"' for column in columns]
    names = ",".join(f'"{column}"' for column in columns)
    conn.execute(create_sql)
    conn.execute(
        f'INSERT INTO "{temp}" ({names}) SELECT {",".join(projections)} '
        f'FROM "{table}"',
        tuple(parameters),
    )
    conn.execute(f'DROP TABLE "{table}"')
    conn.execute(f'ALTER TABLE "{temp}" RENAME TO "{table}"')
    for index_sql in indexes:
        conn.execute(str(index_sql))


def _install_target_constraints(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    for table in DEPENDENT_TABLES:
        if not _table_exists(conn, table):
            continue
        conn.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT '
            f'"{table}_target_environment_id_fkey" FOREIGN KEY '
            "(target_environment_id) REFERENCES environments(id)"
        )
        if table in {"deployment_flows", "deployment_runs"}:
            conn.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT '
                f'"{table}_target_tier_vocabulary" CHECK '
                "(target_tier IS NULL OR target_tier IN ('persistent','ephemeral'))"
            )
            conn.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT '
                f'"{table}_target_tier_environment" CHECK '
                "((target_tier IS NOT NULL AND target_tier='persistent') "
                "= (target_environment_id IS NOT NULL))"
            )


def rebuild_registry(conn: Any) -> None:
    """Replace text keys and every dependent reference in one transaction."""
    if registry_is_numeric(conn):
        return
    if _table_exists(conn, LEGACY_SITES) or _table_exists(conn, LEGACY_ENVIRONMENTS):
        raise RuntimeError("numeric environment/site key cutover is partially present")
    conn.execute("DROP VIEW IF EXISTS item_progress_view")
    _drop_target_constraints(conn)
    _drop_registry_constraints(conn)
    conn.execute(f"ALTER TABLE environments RENAME TO {LEGACY_ENVIRONMENTS}")
    conn.execute(f"ALTER TABLE sites RENAME TO {LEGACY_SITES}")
    execute_schema_script(conn, _NEW_REGISTRY_SQL)
    site_ids, site_names = _copy_sites(conn)
    env_ids, env_names = _copy_environments(conn, site_ids)
    _rewrite_dependent_columns(conn, env_ids)
    recode_stored_references(conn, env_names, site_names)
    conn.execute(f"DROP TABLE {LEGACY_ENVIRONMENTS}")
    conn.execute(f"DROP TABLE {LEGACY_SITES}")
    _install_target_constraints(conn)
    from yoke_core.domain.flow_init import create_or_replace_item_progress_view
    create_or_replace_item_progress_view(conn, commit=False)


__all__ = ["DEPENDENT_TABLES", "rebuild_registry", "registry_is_numeric"]
