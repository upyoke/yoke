"""Structured launch-name derivation tests."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.session_launch_assignment import assignment_session_name
from yoke_core.domain.session_launch_types import SessionLaunchError


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, name TEXT, "
        "public_item_prefix TEXT)"
    )
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER, "
        "project_sequence INTEGER, title TEXT)"
    )
    conn.execute(
        "INSERT INTO projects VALUES "
        "(1,'yoke','Yoke','YOK'),(2,'app','App','APP')"
    )
    conn.execute("INSERT INTO items VALUES (42,1,2580,'Record session presentation')")
    return conn


def test_name_comes_from_item_identity_and_title_columns():
    conn = _connection()
    assert (
        assignment_session_name(
            conn,
            item_ref="YOK-2580",
            project_id=1,
        )
        == "YOK-2580: Record session presentation"
    )


def test_cross_project_assignment_is_refused():
    conn = _connection()
    with pytest.raises(SessionLaunchError) as raised:
        assignment_session_name(conn, item_ref="YOK-2580", project_id=2)
    assert raised.value.code == "assignment_project_mismatch"
