"""Recode stored JSON references during the numeric environment cutover."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row, strict=True))
        for row in cursor.fetchall()
    ]


def _recode_value(
    value: Any,
    env_names: Mapping[str, str],
    site_names: Mapping[str, str],
) -> Any:
    if isinstance(value, list):
        return [_recode_value(child, env_names, site_names) for child in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, child in value.items():
        if key == "environment_by_target":
            # The numeric-key cutover deletes the alias map. Registered
            # environment names are now the complete release-pin vocabulary.
            continue
        new_key = str(key)
        new_child = _recode_value(child, env_names, site_names)
        token = str(child) if not isinstance(child, (dict, list)) else ""
        if key in {"environment_id", "target_environment_id"} and token in env_names:
            new_key = "environment" if key == "environment_id" else "target_environment"
            new_child = env_names[token]
        elif key == "site_id" and token in site_names:
            new_key = "site"
            new_child = site_names[token]
        elif key == "migration_receipts" and isinstance(child, dict):
            new_child = {
                site_names.get(str(site), str(site)): receipt
                for site, receipt in child.items()
            }
        if new_key in out and out[new_key] != new_child:
            raise AssertionError(f"environment reference recode collides on {new_key!r}")
        out[new_key] = new_child
    return out


def _recode_json_column(
    conn: Any,
    table: str,
    key_column: str,
    json_column: str,
    env_names: Mapping[str, str],
    site_names: Mapping[str, str],
) -> None:
    if not _table_exists(conn, table) or not _column_exists(conn, table, json_column):
        return
    p = _p(conn)
    for row in _rows(conn.execute(
        f'SELECT "{key_column}" AS row_key,"{json_column}" AS document '
        f'FROM "{table}" WHERE "{json_column}" IS NOT NULL'
    )):
        try:
            before = json.loads(str(row["document"]))
        except (TypeError, ValueError):
            continue
        after = _recode_value(before, env_names, site_names)
        if after != before:
            conn.execute(
                f'UPDATE "{table}" SET "{json_column}"={p} '
                f'WHERE "{key_column}"={p}',
                (json.dumps(after, separators=(",", ":")), row["row_key"]),
            )


def _recode_execution_targets(
    conn: Any,
    table: str,
    env_names: Mapping[str, str],
    site_names: Mapping[str, str],
) -> None:
    if not _table_exists(conn, table) or not _column_exists(
        conn, table, "execution_target_json"
    ):
        return
    p = _p(conn)
    for row in _rows(conn.execute(
        f'SELECT id,execution_target_json FROM "{table}" '
        "WHERE execution_target_json IS NOT NULL"
    )):
        target = json.loads(str(row["execution_target_json"]))
        site = dict(target.get("site") or {})
        environment = dict(target.get("environment") or {})
        old_site = str(site.pop("id", ""))
        old_env = str(environment.pop("id", ""))
        if old_site in site_names:
            site["name"] = site_names[old_site]
        if old_env in env_names:
            environment["name"] = env_names[old_env]
        target.update({"schema": 2, "site": site, "environment": environment})
        encoded = json.dumps(target, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        conn.execute(
            f'UPDATE "{table}" SET execution_target_json={p},'
            f'execution_target_digest={p} WHERE id={p}',
            (encoded, digest, row["id"]),
        )


def recode_stored_references(
    conn: Any,
    env_names: Mapping[str, str],
    site_names: Mapping[str, str],
) -> None:
    for table, key, column in (
        ("project_capabilities", "id", "settings"),
        ("sites", "id", "settings"),
        ("environments", "id", "settings"),
        ("qa_plan_cases", "id", "method_config"),
        ("qa_requirements", "id", "method_config"),
        ("qa_plan_executions", "id", "roster_json"),
        ("qa_plan_execution_results", "execution_id", "result_json"),
        ("events", "id", "envelope"),
    ):
        _recode_json_column(conn, table, key, column, env_names, site_names)
    for table in ("qa_requirements", "qa_plan_executions"):
        _recode_execution_targets(conn, table, env_names, site_names)


__all__ = ["recode_stored_references"]
