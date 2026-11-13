"""Every boot strips retired settings keys from every project's rows.

Per-project repair (upsert, board read, install) reaches only projects in
use, so a retired project kept a retired key until the release invariant
that checks every ``project_capabilities`` row refused the fleet rehearsal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.project_policy_capabilities import (
    drop_retired_capability_keys,
)
from yoke_core.domain.schema_init import converge_core_schema

_RETIRED_PROJECT = 9014
_UNPARSEABLE = '{"disposable_generated_paths": ['


class _UpdateRecorder:
    """Pass-through connection that records every UPDATE it is given."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.updates: list[str] = []

    def execute(self, sql: str, *args: Any) -> Any:
        if sql.lstrip().upper().startswith("UPDATE"):
            self.updates.append(sql)
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _seed(conn: Any) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, retired_at, created_at) "
        "VALUES (%s, 'retired-one', 'Retired One', now(), now())",
        (_RETIRED_PROJECT,),
    )
    rows = (
        ("project-policy", {"disposable_generated_paths": ["dist"], "x": 1}),
        ("pulumi-state", {"runner_fleet_stack_name": "old", "state_bucket": "b"}),
    )
    for cap_type, settings in rows:
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES (%s, %s, %s, now())",
            (_RETIRED_PROJECT, cap_type, json.dumps(settings)),
        )
    conn.commit()


def _raw(conn: Any, project_id: int, cap_type: str) -> str:
    row = conn.execute(
        "SELECT settings FROM project_capabilities WHERE project_id=%s AND type=%s",
        (project_id, cap_type),
    ).fetchone()
    assert row is not None
    return row["settings"] if isinstance(row, dict) else row[0]


@pytest.fixture()
def named_restore_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RESTORE_POINT_ENV, "snapshot:retired-keys-boot-test")


def test_boot_strips_retired_keys_from_a_retired_project(
    tmp_path: Path, named_restore_point: None
) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _seed(conn)
            converge_core_schema(conn)

            policy = _raw(conn, _RETIRED_PROJECT, "project-policy")
            assert json.loads(policy) == {"x": 1}
            pulumi = _raw(conn, _RETIRED_PROJECT, "pulumi-state")
            assert json.loads(pulumi) == {"state_bucket": "b"}

            recorder = _UpdateRecorder(conn)
            drop_retired_capability_keys(recorder)
            assert recorder.updates == []
        finally:
            conn.close()


def test_boot_leaves_an_unparseable_row_untouched(
    tmp_path: Path, named_restore_point: None
) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _seed(conn)
            conn.execute(
                "UPDATE project_capabilities SET settings=%s "
                "WHERE project_id=%s AND type='project-policy'",
                (_UNPARSEABLE, _RETIRED_PROJECT),
            )
            conn.commit()
            converge_core_schema(conn)

            assert _raw(conn, _RETIRED_PROJECT, "project-policy") == _UNPARSEABLE
            pulumi = _raw(conn, _RETIRED_PROJECT, "pulumi-state")
            assert json.loads(pulumi) == {"state_bucket": "b"}
        finally:
            conn.close()
