# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from uuid import uuid4

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    BRANCH_MACHINE_ONLY,
    OPERATION_INIT,
    ROW_IDS,
    SCHEMA_NAME,
    STATUS_CONFIGURED,
    STATUS_DEFERRED,
    STATUS_VERIFIED,
)

from yoke_core.domain import project_onboarding_runs


def _conn() -> Any:
    """A bare database plus the onboarding tables, built by the fixture.

    ``converge_core_schema`` creates these tables on every boot, so serving
    code reaches them already present and no longer converges them itself. A
    minimal database has no converge behind it, which is what
    ``ensure_schema`` is for.
    """
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    project_onboarding_runs.ensure_schema(conn)
    return pg_testdb.drop_database_on_close(conn, name)
