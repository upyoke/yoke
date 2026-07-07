"""Doctor HC tests (Quality + config HCs).

Other doctor_hc_db_full tests live in sibling files (test_doctor_hc_db_full*.py).

Schema scaffolding shared via _doctor_hc_db_full_test_helpers (private module).
"""

from __future__ import annotations

import os

from unittest.mock import patch

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor import (
    hc_backlog_quality,
    hc_config_validation,
)
from runtime.api.conftest import (
    insert_deployment_run,
    insert_event,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _add_deployment_preview_environments_table,
    _add_ephemeral_environments_table,
    _default_args,
    _result,
    _run_hc,
)


def _unconstrained_priority_conn():
    """Items table without the priority CHECK constraint, simulating
    legacy rows with NULL/invalid priority values."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, title TEXT, type TEXT, status TEXT,
            priority TEXT, spec TEXT, created_at TEXT, updated_at TEXT
        );
        """,
    )
    return conn


class TestHCBacklogQualityFull:
    """Comprehensive tests for HC-backlog-quality (stale ideas, short titles, bodies, priority)."""

    def test_stale_idea_triggers_warn(self, test_db):
        """Test 1: Stale idea (older than 30 days) triggers WARN."""
        insert_item(test_db, id=1, title="A stale old idea item for testing",
                    status="idea", created_at="2025-12-01T00:00:00Z", spec="Some body content")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result in ("WARN", "FAIL")
        assert "YOK-1: stale idea" in r.detail

    def test_recent_idea_no_stale_warn(self, test_db):
        """Test 2: Recent idea does NOT trigger stale WARN."""
        insert_item(test_db, id=1, title="A very recent idea item",
                    status="idea", created_at="2099-01-01T00:00:00Z", spec="Some body content")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert "stale idea" not in r.detail

    def test_short_title_triggers_warn(self, test_db):
        """Test 3: Title too short (< 10 chars) triggers WARN."""
        insert_item(test_db, id=1, title="Fix bug",
                    status="implementing", created_at="2026-02-24T00:00:00Z", spec="Some body content")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result in ("WARN", "FAIL")
        assert "YOK-1: title too short" in r.detail

    def test_bodyless_active_triggers_fail(self, test_db):
        """Test 4: Body-less active item triggers FAIL."""
        insert_item(test_db, id=1, title="A perfectly good title for testing",
                    status="implementing", created_at="2026-02-24T00:00:00Z", spec="")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "no body content at status" in r.detail

    def test_missing_priority_triggers_warn(self, test_db):
        """Test 5: Missing/NULL priority triggers WARN.

        The conftest schema has a CHECK constraint on priority, so we create a
        separate in-memory connection without that constraint to simulate legacy
        data with NULL/invalid priority values.
        """
        conn = _unconstrained_priority_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, spec, created_at, updated_at) "
            "VALUES (1, 'A valid title with enough length', 'issue', 'implementing', "
            "NULL, 'Some body content', '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z')"
        )
        conn.commit()
        rec = _run_hc(hc_backlog_quality, conn)
        r = _result(rec)
        assert r.result in ("WARN", "FAIL")
        assert "YOK-1: missing priority" in r.detail
        conn.close()

    def test_custom_stale_days_config(self, test_db, tmp_path):
        """Test 6: Custom backlog_stale_days config overrides default."""
        # Create config file with custom threshold
        yoke_dir = tmp_path / "data"
        yoke_dir.mkdir()
        (yoke_dir / "config").write_text("backlog_stale_days=5\n")

        insert_item(test_db, id=1, title="An idea older than custom threshold",
                    status="idea", created_at="2026-02-14T00:00:00Z", spec="Some body content")

        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_backlog_quality, test_db)

        r = _result(rec)
        assert r.result in ("WARN", "FAIL")
        assert "stale idea" in r.detail
        assert "threshold: 5" in r.detail

    def test_pass_when_all_healthy(self, test_db):
        """Test 7: HC-backlog-quality PASS when all items are healthy."""
        insert_item(test_db, id=1, title="A perfectly healthy backlog item",
                    status="implementing", created_at="2026-02-24T00:00:00Z", spec="Has a proper body")
        insert_item(test_db, id=2, title="Another healthy completed item",
                    status="done", priority="high",
                    created_at="2026-02-20T00:00:00Z", spec="Also has a body")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result == "PASS"

    def test_idea_status_all_subchecks_warn_not_fail(self, test_db):
        """Test 8: Idea-status item with all sub-checks fires WARN not FAIL.

        Uses a bare schema to simulate legacy data with NULL priority.
        """
        conn = _unconstrained_priority_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, spec, created_at, updated_at) "
            "VALUES (1, 'Bad', 'issue', 'idea', NULL, '', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z')"
        )
        conn.commit()
        rec = _run_hc(hc_backlog_quality, conn)
        r = _result(rec)
        # Body-less idea should WARN, not FAIL
        assert r.result == "WARN"
        conn.close()

    def test_bodyless_defined_triggers_fail(self, test_db):
        """Test 9: Body-less defined item triggers FAIL."""
        insert_item(test_db, id=1, title="A defined item without body content",
                    status="refined-idea", created_at="2026-02-24T00:00:00Z", spec="")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "no body content at status" in r.detail

    def test_bodyless_idea_triggers_warn_not_fail(self, test_db):
        """Test 10: Body-less idea item triggers WARN not FAIL."""
        insert_item(test_db, id=1, title="An idea item without body content",
                    status="idea", created_at="2026-02-24T00:00:00Z", spec="")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "no body content (idea" in r.detail

    def test_default_only_body_detected_as_empty(self, test_db):
        """Test 11: Default-only body (just '# Title') detected as empty."""
        insert_item(test_db, id=1, title="A defined item with default body",
                    status="refined-idea", created_at="2026-02-24T00:00:00Z",
                    spec="# A defined item with default body")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "no body content at status" in r.detail

    def test_real_body_passes(self, test_db):
        """Test 12: Item with real body content beyond default heading passes."""
        insert_item(test_db, id=1, title="A defined item with real body",
                    status="refined-idea", created_at="2026-02-24T00:00:00Z",
                    spec="# A defined item with real body\n\nThis has actual content explaining what needs to be done.")
        rec = _run_hc(hc_backlog_quality, test_db)
        r = _result(rec)
        assert "no body content" not in r.detail


class TestHCConfigValidationFull:
    """Tests for HC-config-validation's machine config shape check."""

    def _write_machine_config(self, tmp_path, text):
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text)
        return config_path

    def test_valid_machine_config_passes(self, test_db, tmp_path):
        config_path = self._write_machine_config(
            tmp_path,
            '{"settings": {"base_branch": "main"}, "projects": {}}\n',
        )
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation, test_db)
        assert _result(rec).result == "PASS"

    def test_missing_machine_config_warns(self, test_db, tmp_path):
        config_path = tmp_path / ".yoke" / "config.json"
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "machine config not found" in r.detail

    def test_invalid_machine_config_shape_warns(self, test_db, tmp_path):
        config_path = self._write_machine_config(
            tmp_path,
            '{"settings": {}, "projects": []}\n',
        )
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "projects must be an object" in r.detail
