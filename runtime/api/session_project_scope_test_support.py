# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import unittest

from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)

from runtime.api.fixtures import pg_testdb

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

from yoke_core.domain.session_project_scope import (
    parse_project_cli_arg,
    resolve_session_project_scope,
)


def _make_disposable_db():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name),
        name,
    )
