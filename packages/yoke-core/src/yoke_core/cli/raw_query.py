"""Python owner for the raw-SQL escape hatch exposed via the DB router.

Implements the ``query`` domain behind
``python3 -m yoke_core.cli.db_router query``.

Preserved contract
==================

Invocation::

    python3 -m yoke_core.cli.raw_query "SELECT ..."
    python3 -m yoke_core.cli.raw_query -separator '|' "SELECT ..."

Semantics
---------

* Default column separator is ``|`` (matches sqlite3 CLI list mode).
* The ``-separator VALUE`` leading option overrides the separator, e.g.
  ``-separator ';' "SELECT ..."``.
* Connection is opened against the selected Postgres authority.
* Result rows are printed one per line, columns joined by the separator.
  NULL columns render as the empty string (sqlite3 CLI behavior).
* DDL / DML statements commit their change and print nothing — matching
  ``sqlite3`` CLI when ``cursor.description`` is ``None``.
* SQL errors print ``Error: <message>`` on stderr and return exit 1.
* Missing SQL argument prints the shell's usage block and returns exit 2.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Iterable, List, Optional, TextIO, Tuple

from yoke_core.cli.raw_query_catalog import (
    all_table_names,
    columns_for_table,
    match_pg_undefined_column,
    match_pg_undefined_relation,
)

DEFAULT_SEPARATOR = "|"

# Capture the bare table token from FROM / JOIN. An alias (if any) is
# extracted in a separate post-match step so the regex never swallows
# a following SQL keyword (``JOIN``, ``WHERE``, ...) as an alias.
_TABLE_NAME_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE,
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Keywords that may immediately follow a table name and must never be treated
# as an alias. Anything else is a candidate alias.
_NOT_AN_ALIAS = frozenset({
    "ON", "WHERE", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "JOIN",
    "GROUP", "ORDER", "HAVING", "LIMIT", "UNION", "INTERSECT", "EXCEPT",
    "USING", "NATURAL", "AS",
})
# Preserve the alias prefix on no-such-column so the hinter can resolve it
# back to the right joined table.
_NO_SUCH_COLUMN_RE = re.compile(r"^no such column:\s*(?:(\w+)\.)?(\w+)\s*$")
_NO_SUCH_TABLE_RE = re.compile(r"^no such table:\s*(\w+)\s*$")


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("utf-8", "replace")
    return str(value)


def execute_query(
    sql: str,
    *,
    separator: str = DEFAULT_SEPARATOR,
    db_path: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    """Execute *sql* against the Yoke DB and print the results.

    Parameters
    ----------
    sql:
        Raw SQL string. No multiplexing of multiple statements is
        performed — ``sqlite3.Connection.execute`` accepts a single
        statement, matching the usage pattern of the shell branch where
        callers pass one statement per invocation.
    separator:
        Column separator (default ``|``).
    """
    from yoke_core.domain import db_backend

    try:
        # connect_psycopg routes through the connected-env readiness boundary:
        # a dead local tunnel (env-keyed local-postgres env, e.g. under a
        # YOKE_ENV override) is self-healed and the open retried once
        # instead of surfacing a raw connection-refused.
        conn = db_backend.connect_psycopg()
    except Exception as exc:
        print("Error: {}".format(exc), file=err)
        return 1

    try:
        try:
            cursor = conn.execute(sql)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            hint = _schema_hint(conn, sql, exc)
            if hint:
                print("Error: {}\n{}".format(exc, hint), file=err)
            else:
                print("Error: {}".format(exc), file=err)
            return 1

        if cursor.description is not None:
            for row in cursor.fetchall():
                line = separator.join(_format_cell(col) for col in row)
                out.write(line)
                out.write("\n")
        conn.commit()
    finally:
        conn.close()
    return 0


def _extract_table_refs(sql: str) -> List[Tuple[str, Optional[str]]]:
    """Return ``(table_name, alias_or_None)`` pairs for FROM / JOIN clauses.

    Aliases are inferred from the token immediately following the table
    reference. Bare keywords (``JOIN``, ``WHERE``, ``INNER``, ...) are
    never treated as aliases, even when they follow without ``AS``.
    """
    refs: List[Tuple[str, Optional[str]]] = []
    for m in _TABLE_NAME_RE.finditer(sql):
        table = m.group(1)
        alias = None
        tail = sql[m.end():].lstrip()
        if tail[:2].upper() == "AS" and (len(tail) == 2 or not tail[2].isalnum()):
            tail = tail[2:].lstrip()
        tok = _IDENT_RE.match(tail)
        if tok and tok.group(0).upper() not in _NOT_AN_ALIAS:
            alias = tok.group(0)
        refs.append((table, alias))
    return refs


def _extract_tables(sql: str) -> List[str]:
    """Pull bare table names out of FROM / JOIN clauses."""
    return [t for t, _ in _extract_table_refs(sql)]


def _resolve_alias(
    refs: List[Tuple[str, Optional[str]]], prefix: str,
) -> Optional[str]:
    """Map an alias or table-name prefix back to the joined table name.

    Returns the resolved table name (the alias's underlying table, or the
    table itself when ``prefix`` matches a table directly). Returns ``None``
    when the prefix matches nothing in the query.
    """
    if not prefix:
        return None
    norm = prefix.lower()
    for table, alias in refs:
        if alias and alias.lower() == norm:
            return table
    for table, _ in refs:
        if table.lower() == norm:
            return table
    return None


def _schema_hint(
    conn: Any, sql: str, exc: BaseException,
) -> str:
    """Return a schema hint for the most common shape mistakes.

    ``no such column: alias.X`` → resolve ``alias`` against the query's
    FROM / JOIN clauses and list columns of the resolved table.
    ``no such column: X`` (no prefix) in a single-table query → list that
    table's columns; in a multi-table query → list columns of every joined
    table on separate lines so the operator can spot the right home.
    ``no such table: T`` → ``Valid tables: ...`` (first 30 names).
    Empty string when no useful hint is available.
    """
    msg = str(exc).strip()
    m = _NO_SUCH_COLUMN_RE.match(msg)
    pg_col = None if m else match_pg_undefined_column(msg)
    if m or pg_col:
        prefix = m.group(1) if m else pg_col[0]
        refs = _extract_table_refs(sql)
        if prefix:
            resolved = _resolve_alias(refs, prefix)
            if resolved:
                cols = columns_for_table(conn, resolved)
                if cols:
                    return "Valid columns on {}: {}".format(
                        resolved, ", ".join(cols),
                    )
            # Alias did not resolve — fall through to multi-table listing.
        tables = [t for t, _ in refs]
        if len(tables) == 1:
            cols = columns_for_table(conn, tables[0])
            if cols:
                return "Valid columns on {}: {}".format(
                    tables[0], ", ".join(cols),
                )
            return ""
        lines: List[str] = []
        for table in tables:
            cols = columns_for_table(conn, table)
            if cols:
                lines.append(
                    "Valid columns on {}: {}".format(table, ", ".join(cols)),
                )
        return "\n".join(lines)
    m = _NO_SUCH_TABLE_RE.match(msg)
    if m or match_pg_undefined_relation(msg):
        names = all_table_names(conn)
        if not names:
            return ""
        head = ", ".join(names[:30])
        more = "" if len(names) <= 30 else " ... ({} more)".format(len(names) - 30)
        return "Valid tables: {}{}".format(head, more)
    return ""


USAGE_ERR_MSG = "Error: query requires a SQL string"
USAGE_LINE = 'Usage: python3 -m yoke_core.cli.db_router query [-separator S] "SELECT ..."'

USAGE_DETAIL = """\
Raw SQL escape hatch against the selected Yoke Postgres authority.

Worked example (item lookup by YOK-N — the `item_id` column is integer):
  python3 -m yoke_core.cli.db_router query \\
    "SELECT id, status, title FROM items WHERE id = 1791"

  python3 -m yoke_core.cli.db_router query -separator '|' \\
    "SELECT id, state, item_id FROM path_claims WHERE item_id = 1791"

Options:
  -separator S  Column separator (default `|`, matches sqlite3 CLI list mode).

Rules and gotchas:
  - One statement per invocation (no multi-statement multiplexing).
  - DDL/DML commits its change and prints nothing.
  - YOK-N never appears as a literal in SQL: items.id is integer; strip the
    prefix and pass the bare number.
  - Prefer `!=`-free SQL: use `<>` per the project's raw-SQL convention.
  - Authority comes from the connected Postgres env / DSN binding; never
    construct or open `data/yoke.db`.

Exit codes: 0 success, 1 DB-missing / SQL error, 2 usage error.
"""


def _print_usage(err: TextIO) -> None:
    print(USAGE_ERR_MSG, file=err)
    print(USAGE_LINE, file=err)


def _print_help(out: TextIO) -> None:
    print(USAGE_LINE, file=out)
    print("", file=out)
    print(USAGE_DETAIL, file=out, end="")


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    # Resolve streams at call time so redirect_stdout/stderr context
    # managers (and other late patches) are honored.
    out = sys.stdout
    err = sys.stderr

    if args and args[0] in ("-h", "--help", "help"):
        _print_help(out)
        return 0

    if not args:
        _print_usage(err)
        return 2

    separator = DEFAULT_SEPARATOR

    if args[0] == "-separator":
        if len(args) < 3:
            _print_usage(err)
            return 2
        separator = args[1]
        args = args[2:]

    if not args or not args[0]:
        _print_usage(err)
        return 2

    sql = args[0]
    return execute_query(sql, separator=separator, out=out, err=err)


if __name__ == "__main__":
    sys.exit(main())
