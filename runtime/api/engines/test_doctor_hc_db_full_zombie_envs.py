"""Doctor HC tests for zombie ephemeral environments."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.engines.doctor import hc_zombie_ephemeral_envs
from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _add_ephemeral_environments_table,
    _result,
    _run_hc,
)


_EXTRA_PROJECT_IDS = {
    "proj-a": 10,
    "proj-b": 11,
    "proj-c": 12,
    "proj-d": 13,
}


def _hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _project_id(slug: str) -> int:
    return {"yoke": 1, "buzz": 2, **_EXTRA_PROJECT_IDS}[slug]


def _seed_project(conn, slug: str) -> None:
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, created_at, public_item_prefix) "
        "VALUES (%s, %s, %s, %s, 'YOK') "
        "ON CONFLICT (id) DO UPDATE SET "
        "slug=EXCLUDED.slug, name=EXCLUDED.name",
        (
            _project_id(slug),
            slug,
            slug,
            "2026-01-01T00:00:00Z",
        ),
    )


class TestHCZombieEphemeralEnvsFull:
    """Tests for HC-zombie-ephemeral-envs."""

    def _setup(self, conn):
        _add_ephemeral_environments_table(conn)
        for slug in _EXTRA_PROJECT_IDS:
            _seed_project(conn, slug)

    def test_pass_no_envs(self, test_db):
        self._setup(test_db)
        rec = _run_hc(hc_zombie_ephemeral_envs, test_db)
        assert _result(rec).result == "PASS"

    def test_pass_recent_envs(self, test_db):
        self._setup(test_db)
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (_project_id("proj-a"), "feature/foo", "running", _hours_ago(1)),
        )
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (_project_id("proj-a"), "feature/bar", "healthy", _hours_ago(2)),
        )
        test_db.commit()
        rec = _run_hc(hc_zombie_ephemeral_envs, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_zombie_envs(self, test_db):
        self._setup(test_db)
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (_project_id("proj-b"), "feature/zombie", "running", _hours_ago(6)),
        )
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (_project_id("proj-c"), "feature/stale", "starting", _hours_ago(10)),
        )
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (
                _project_id("proj-d"),
                "feature/stuck-pending",
                "pending",
                _hours_ago(5),
            ),
        )
        test_db.commit()
        rec = _run_hc(hc_zombie_ephemeral_envs, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "proj-b" in r.detail
        assert "feature/zombie" in r.detail
        assert "proj-c" in r.detail
        assert "feature/stale" in r.detail
        assert "proj-d" in r.detail
        assert "feature/stuck-pending" in r.detail

    def test_stopped_failed_not_flagged(self, test_db):
        self._setup(test_db)
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at, stopped_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                _project_id("proj-d"),
                "feature/old-stopped",
                "stopped",
                _hours_ago(48),
                _hours_ago(47),
            ),
        )
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at, stopped_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                _project_id("proj-d"),
                "feature/old-failed",
                "failed",
                _hours_ago(24),
                _hours_ago(23),
            ),
        )
        test_db.commit()
        rec = _run_hc(hc_zombie_ephemeral_envs, test_db)
        assert _result(rec).result == "PASS"

    def test_pass_no_table(self, test_db):
        rec = _run_hc(hc_zombie_ephemeral_envs, test_db)
        assert _result(rec).result == "PASS"
