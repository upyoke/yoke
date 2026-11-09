"""Schema dialect adaptation remains independent of connection factories."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import ast
from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain import db_backend, db_helpers, schema_connection
from yoke_core.domain.schema_init_apply import execute_schema_script


@pytest.mark.parametrize("wrapper", [None, "_inner", "_conn"])
def test_existing_sqlite_connections_keep_their_dialect(wrapper):
    with sqlite3.connect(":memory:") as conn:
        target = conn if wrapper is None else SimpleNamespace(**{wrapper: conn})
        assert not schema_connection.connection_is_postgres(target)
        instant = datetime(2026, 1, 2, 3, tzinfo=timezone(timedelta(hours=3)))
        assert schema_connection.instant_parameter(target, instant) == "2026-01-02T00:00:00.000000Z"


def test_postgres_instant_parameters_stay_native_and_utc():
    conn = object()
    instant = datetime(2026, 1, 2, 3, tzinfo=timezone(timedelta(hours=3)))
    assert schema_connection.connection_is_postgres(conn)
    assert schema_connection.instant_parameter(conn, instant) == datetime(
        2026, 1, 2, tzinfo=timezone.utc
    )
    assert schema_connection.instant_parameter(conn, None) is None


@pytest.mark.parametrize("invalid", ["2026-01-02T00:00:00Z", 123, datetime(2026, 1, 2)])
def test_instant_parameters_refuse_unparsed_or_naive_values(invalid):
    with pytest.raises((TypeError, ValueError)):
        schema_connection.instant_parameter(object(), invalid)


def test_existing_import_surfaces_share_the_schema_implementation():
    assert db_backend.connection_is_postgres is schema_connection.connection_is_postgres
    assert db_helpers.instant_parameter is schema_connection.instant_parameter


def test_schema_script_uses_the_injected_sqlite_connection():
    with sqlite3.connect(":memory:") as conn:
        execute_schema_script(conn, "CREATE TABLE sample (id INTEGER PRIMARY KEY); INSERT INTO sample VALUES (7);")
        assert conn.execute("SELECT id FROM sample").fetchone() == (7,)


@pytest.mark.parametrize("module", ["schema_common", "schema_init_apply", "schema_events", "qa_schema", "schema_connection"])
def test_schema_helpers_do_not_import_connection_factories(module):
    root = Path(schema_connection.__file__).parent
    tree = ast.parse((root / f"{module}.py").read_text())
    imports = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    imports += [
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    ]
    assert "yoke_core.domain.db_backend" not in imports
    assert "yoke_core.domain.db_helpers" not in imports
    assert not any(
        alias.name in {"db_backend", "db_helpers"}
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "yoke_core.domain"
        for alias in node.names
    )
