"""Whether the live catalog already holds what one schema statement would make.

Postgres takes a table's lock before it notices that a ``CREATE ... IF NOT
EXISTS`` or ``ADD COLUMN IF NOT EXISTS`` has nothing to do, so the additive
converge asks the catalog first (:mod:`yoke_core.domain.schema_converge_statements`).
Every check reads ``pg_catalog`` and resolves names through ``search_path``,
the way the statement itself would.
"""

from __future__ import annotations

from typing import Any, Optional

from pglast import ast
from pglast.enums import AlterTableType, ObjectType
from pglast.stream import RawStream


def _one(conn: Any, sql: str, params: tuple) -> Optional[tuple]:
    return conn.execute(sql, params).fetchone()


def object_name(value: Any) -> str:
    return ".".join(part.sval for part in value) if isinstance(value, tuple) else value


def _relation_exists(conn: Any, name: str) -> bool:
    return _one(conn, "SELECT to_regclass(%s)", (name,))[0] is not None


def _attribute(conn: Any, table: str, column: str) -> Optional[tuple]:
    return _one(
        conn,
        "SELECT attnotnull FROM pg_attribute WHERE attrelid = to_regclass(%s) "
        "AND attname = %s AND attnum > 0 AND NOT attisdropped",
        (table, column),
    )


def _constraint_exists(conn: Any, table: str, name: str) -> bool:
    return (
        _one(
            conn,
            "SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass(%s) "
            "AND conname = %s",
            (table, name),
        )
        is not None
    )


def _trigger_exists(conn: Any, table: str, name: str) -> bool:
    return (
        _one(
            conn,
            "SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass(%s) "
            "AND tgname = %s AND NOT tgisinternal",
            (table, name),
        )
        is not None
    )


def _table_name(relation: ast.RangeVar) -> str:
    if relation.schemaname:
        return f"{relation.schemaname}.{relation.relname}"
    return relation.relname


def _alter_command_satisfied(conn: Any, table: str, cmd: ast.AlterTableCmd) -> bool:
    kind = cmd.subtype
    if kind == AlterTableType.AT_AddColumn and cmd.missing_ok:
        return _attribute(conn, table, cmd.def_.colname) is not None
    if kind == AlterTableType.AT_DropColumn and cmd.missing_ok:
        return _attribute(conn, table, cmd.name) is None
    if kind in (AlterTableType.AT_DropNotNull, AlterTableType.AT_SetNotNull):
        attribute = _attribute(conn, table, cmd.name)
        wants_not_null = kind == AlterTableType.AT_SetNotNull
        return attribute is not None and bool(attribute[0]) == wants_not_null
    if kind == AlterTableType.AT_DropConstraint and cmd.missing_ok:
        return not _constraint_exists(conn, table, cmd.name)
    if kind == AlterTableType.AT_AddConstraint and cmd.def_.conname:
        return _constraint_exists(conn, table, cmd.def_.conname)
    return False


def _function_body(stmt: ast.CreateFunctionStmt) -> Optional[str]:
    for option in stmt.options or ():
        if option.defname == "as" and len(option.arg) == 1:
            return option.arg[0].sval
    return None


def _function_unchanged(conn: Any, stmt: ast.CreateFunctionStmt) -> bool:
    body = _function_body(stmt)
    if not stmt.replace or body is None:
        return False
    name = object_name(stmt.funcname).split(".")[-1]
    return (
        _one(
            conn,
            "SELECT 1 FROM pg_proc WHERE proname = %s AND prosrc = %s "
            "AND pronargs = %s AND pronamespace = current_schema()::regnamespace",
            (name, body, len(stmt.parameters or ())),
        )
        is not None
    )


_VIEW_PROBE = "yoke_converge_view_probe"

#: One view's normalised definition and its ordered output columns.
_VIEW_SHAPE_SQL = (
    "SELECT pg_get_viewdef(to_regclass(%s)), ARRAY(SELECT attname || ':' || "
    "atttypid::regtype::text FROM pg_attribute WHERE attrelid = to_regclass(%s) "
    "AND attnum > 0 ORDER BY attnum)"
)


def _view_unchanged(conn: Any, stmt: ast.ViewStmt) -> bool:
    """Compare a replaced view with the same query built as a temporary view.

    Postgres normalises a view's text when it stores it, so the comparison is
    between two stored definitions, never between stored and authored text.
    The temporary probe reads its source tables' shape and takes no lock a
    writer waits on.
    """
    name = _table_name(stmt.view)
    if not stmt.replace or not _relation_exists(conn, name):
        return False
    probe = ast.ViewStmt(
        view=ast.RangeVar(relname=_VIEW_PROBE, relpersistence="t", inh=True),
        aliases=stmt.aliases,
        query=stmt.query,
        options=stmt.options,
        withCheckOption=stmt.withCheckOption,
    )
    conn.execute(RawStream()(probe))
    try:
        live = _one(conn, _VIEW_SHAPE_SQL, (name, name))
        wanted = _one(conn, _VIEW_SHAPE_SQL, (_VIEW_PROBE, _VIEW_PROBE))
    finally:
        conn.execute(f"DROP VIEW {_VIEW_PROBE}")
    return tuple(live) == tuple(wanted)


def _drop_satisfied(conn: Any, stmt: ast.DropStmt) -> bool:
    if not stmt.missing_ok:
        return False
    names = [object_name(obj) for obj in stmt.objects]
    if stmt.removeType in (
        ObjectType.OBJECT_TABLE,
        ObjectType.OBJECT_INDEX,
        ObjectType.OBJECT_VIEW,
        ObjectType.OBJECT_SEQUENCE,
    ):
        return not any(_relation_exists(conn, name) for name in names)
    if stmt.removeType == ObjectType.OBJECT_TRIGGER:
        return not any(_trigger_exists(conn, *name.rsplit(".", 1)) for name in names)
    return False


def statement_is_satisfied(conn: Any, stmt: ast.Node) -> bool:
    """Return whether the live catalog already holds what *stmt* would make."""
    if isinstance(stmt, ast.CreateStmt) and stmt.if_not_exists:
        return _relation_exists(conn, _table_name(stmt.relation))
    if isinstance(stmt, ast.IndexStmt) and stmt.if_not_exists and stmt.idxname:
        return _relation_exists(conn, stmt.idxname)
    if isinstance(stmt, ast.CreateSeqStmt) and stmt.if_not_exists:
        return _relation_exists(conn, _table_name(stmt.sequence))
    if isinstance(stmt, ast.AlterTableStmt) and stmt.objtype == ObjectType.OBJECT_TABLE:
        table = _table_name(stmt.relation)
        if not _relation_exists(conn, table):
            return bool(stmt.missing_ok)
        return all(_alter_command_satisfied(conn, table, cmd) for cmd in stmt.cmds)
    if isinstance(stmt, ast.DropStmt):
        return _drop_satisfied(conn, stmt)
    if isinstance(stmt, ast.CreateFunctionStmt):
        return _function_unchanged(conn, stmt)
    if isinstance(stmt, ast.ViewStmt):
        return _view_unchanged(conn, stmt)
    return False


__all__ = ["object_name", "statement_is_satisfied"]
