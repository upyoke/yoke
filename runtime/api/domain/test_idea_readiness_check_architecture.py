"""Tests for the ARCHITECTURE_IMPACT_UNCERTAIN readiness check."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.idea_readiness_check_architecture import (
    verify_architecture_impact_resolved,
)


def _make_items_conn(architecture_impact=None):
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    if architecture_impact is None:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT)"
        )
        conn.execute("INSERT INTO items (id, title) VALUES (1, 't')")
    else:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, "
            "architecture_impact TEXT NOT NULL DEFAULT 'none')"
        )
        conn.execute(
            "INSERT INTO items (id, title, architecture_impact) "
            "VALUES (1, 't', %s)",
            (architecture_impact,),
        )
    conn.commit()
    return conn


class TestArchitectureImpactReadiness:
    def test_uncertain_emits_issue(self):
        conn = _make_items_conn("uncertain")
        try:
            issues = verify_architecture_impact_resolved(conn, 1)
            assert len(issues) == 1
            issue = issues[0]
            assert issue.code == "ARCHITECTURE_IMPACT_UNCERTAIN"
            assert "uncertain" in issue.message.lower()
            assert "architecture_impact" in issue.remediation
            assert issue.context["current_value"] == "uncertain"
        finally:
            conn.close()

    @pytest.mark.parametrize("value", [
        "none",
        "path_context_only",
        "architecture_model_change",
        "architecture_model_change\n",
    ])
    def test_resolved_values_pass(self, value):
        conn = _make_items_conn(value)
        try:
            assert verify_architecture_impact_resolved(conn, 1) == []
        finally:
            conn.close()

    def test_missing_column_passes_as_none(self):
        """Pre-existing rows on an old schema (no column) read as
        'none' and pass without operator action."""
        conn = _make_items_conn(architecture_impact=None)
        try:
            assert verify_architecture_impact_resolved(conn, 1) == []
        finally:
            conn.close()

    def test_missing_item_passes(self):
        conn = _make_items_conn("none")
        try:
            assert verify_architecture_impact_resolved(conn, 99) == []
        finally:
            conn.close()
