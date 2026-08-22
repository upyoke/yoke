"""Doctor coverage for the closed organization settings registry."""

from __future__ import annotations

import sqlite3

from yoke_core.engines.doctor_hc_organization_settings import (
    HC_SLUG,
    hc_organization_settings,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _run(conn: sqlite3.Connection):
    collector = RecordCollector()
    hc_organization_settings(conn, DoctorArgs(), collector)
    assert len(collector.results) == 1
    return collector.results[0]


def test_skips_before_organization_settings_column_exists() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE organizations (id INTEGER PRIMARY KEY, slug TEXT)")

    assert _run(conn).result == "SKIP"


def test_passes_valid_explicit_overrides() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE organizations "
        "(id INTEGER PRIMARY KEY, slug TEXT, settings TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO organizations VALUES "
        "(1, 'default', '{\"fleet\": {\"relay_poll_seconds\": 30}}')"
    )

    result = _run(conn)
    assert result.check_id == HC_SLUG
    assert result.result == "PASS"


def test_fails_unknown_or_invalid_stored_settings() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE organizations "
        "(id INTEGER PRIMARY KEY, slug TEXT, settings TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO organizations VALUES "
        "(1, 'default', '{\"fleet\": {\"invented\": true}}')"
    )

    result = _run(conn)
    assert result.result == "FAIL"
    assert "invented" in result.detail
