"""Regenerate the serving catalog from a disposable database born by this source.

No live control-plane connection is read or changed. The source-maintainer
command requires an explicit checkout target and uses the existing test
cluster, complete initialization chain, and disposable database lifecycle.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend
from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)
from yoke_core.tools import pg_testcluster


_CATALOG_PATH = Path(
    "packages/yoke-core/src/yoke_core/domain/schema_expected_catalog.py"
)
_TYPES = {"timestamp with time zone": "TIMESTAMPTZ"}


def read_catalog(conn) -> dict[str, dict[str, str]]:
    """Read concrete base-table declarations, excluding derived views."""
    tables: dict[str, dict[str, str]] = defaultdict(dict)
    for table, column, data_type in conn.execute(
        "SELECT c.table_name,c.column_name,c.data_type "
        "FROM information_schema.columns c "
        "JOIN information_schema.tables t "
        "ON t.table_schema=c.table_schema AND t.table_name=c.table_name "
        "WHERE c.table_schema='public' AND t.table_type='BASE TABLE' "
        "ORDER BY c.table_name,c.ordinal_position"
    ).fetchall():
        tables[table][column] = _TYPES.get(data_type, data_type.upper())
    mismatches = {
        f"{table}.{column}": tables.get(table, {}).get(column, "missing")
        for table, column in STORED_INSTANT_COLUMNS
        if tables.get(table, {}).get(column) != "TIMESTAMPTZ"
    }
    if mismatches:
        raise RuntimeError(f"native_instant_catalog_incomplete: {mismatches}")
    return dict(tables)


def replace_declaration(source: str, catalog: dict[str, dict[str, str]]) -> str:
    """Replace only the generated declaration, retaining its parser and teaching."""
    node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_EXPECTED_SCHEMA_STR"
            for target in node.targets
        )
    )
    sections = [
        f"{table}:" + ",".join(f"{name}/{kind}" for name, kind in columns.items())
        for table, columns in catalog.items()
    ]
    declaration = (
        "_EXPECTED_SCHEMA_STR = (\n"
        + "".join(
            "    " + json.dumps(("|" if index else "") + section) + "\n"
            for index, section in enumerate(sections)
        )
        + ")\n"
    )
    lines = source.splitlines(keepends=True)
    return (
        "".join(lines[: node.lineno - 1])
        + declaration
        + "".join(lines[node.end_lineno :])
    )


def render(*, target_root: Path) -> None:
    target = target_root.resolve() / _CATALOG_PATH
    assert_target_under_session_work_authority(target)
    if pg_testcluster.ensure_started() != 0:
        raise RuntimeError("schema_catalog_test_cluster_unavailable")
    # Bind the declared local test cluster before the disposable fixture captures
    # its base identity; never inherit a control-plane connection for this tool.
    import os

    os.environ[db_backend.PG_DSN_ENV] = pg_testcluster.dsn()
    name = pg_testdb.create_test_database(pooled=False)
    try:
        run_init_chain_at_dsn(
            pg_testdb.dsn_for_test_database(name), emit=lambda _: None
        )
        with pg_testdb.connect_test_database(name) as conn:
            catalog = read_catalog(conn)
        target.write_text(replace_declaration(target.read_text(), catalog))
        print(
            f"schema catalog rendered: {len(catalog)} base tables; {len(STORED_INSTANT_COLUMNS)} native instants"
        )
    finally:
        pg_testdb.drop_test_database(name, pooled=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True, type=Path)
    render(target_root=parser.parse_args().target_root)


if __name__ == "__main__":
    main()
