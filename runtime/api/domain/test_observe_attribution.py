"""observe - DB-backed session attribution.

Split out of ``test_observe.py`` to keep authored files under the 350-line
limit.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from yoke_core.domain.observe_test_helpers import (
    _fresh_now,
    observe_attribution_db,
    seed_item,
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db


class TestSessionAttribution(unittest.TestCase):
    """DB-backed session attribution replaces marker files."""

    def test_TC_session_current_attribution(self):
        """Tier 1: current_item_id from harness_sessions -> session_current."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            seed_item(conn, 42, status="implementing")
            now = _fresh_now()
            seed_session(
                conn, "sess_100", current_item_id="42", current_item_set_at=now
            )
            conn.commit()
            conn.close()

            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id="sess_100"
            )
            self.assertEqual(item_id, "42")
            self.assertEqual(source, "session_current")

    def test_TC_existing_db_path_uses_backend_connector(self):
        """Existing files are backend tokens, not raw SQLite read authority."""
        from yoke_core.domain.observe_db_reads import connect_observe_read_db

        sentinel = object()
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            with mock.patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=sentinel,
            ) as connect:
                self.assertIs(connect_observe_read_db(tmp.name), sentinel)
        connect.assert_called_once_with(tmp.name)

    def test_TC_session_recent_attribution(self):
        """Tier 3: recent_item_id from harness_sessions -> session_recent."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            seed_item(conn, 99, status="done")
            # Two active items so active_fallback doesn't trigger (needs exactly 1)
            seed_item(conn, 50, status="implementing")
            seed_item(conn, 51, status="implementing")
            now = _fresh_now()
            seed_session(
                conn, "sess_200", recent_item_id="99", recent_item_recorded_at=now
            )
            conn.commit()
            conn.close()

            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id="sess_200"
            )
            self.assertEqual(item_id, "99")
            self.assertEqual(source, "session_recent")

    def test_TC_session_no_attribution_falls_through(self):
        """No session data -> falls through to None (active_fallback needs exactly 1)."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            # Two active items, no session data -> no attribution
            seed_item(conn, 50, status="implementing")
            seed_item(conn, 51, status="implementing")
            seed_session(conn, "sess_300")
            conn.commit()
            conn.close()

            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id="sess_300"
            )
            self.assertIsNone(item_id)
            self.assertIsNone(source)

    def test_TC_session_active_fallback_unchanged(self):
        """Tier 2: single active item -> active_fallback (unchanged behavior)."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            seed_item(conn, 77, status="implementing")
            seed_session(conn, "sess_400")
            conn.commit()
            conn.close()

            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id="sess_400"
            )
            self.assertEqual(item_id, "77")
            self.assertEqual(source, "active_fallback")

    def test_TC_session_recent_expired_no_match(self):
        """Tier 3: recent_item with old timestamp -> no attribution."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            seed_item(conn, 88, status="done")
            seed_item(conn, 50, status="implementing")
            seed_item(conn, 51, status="implementing")
            # Set recorded_at to 2 hours ago (7200s > 1800s limit)
            two_hours_ago = (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            seed_session(
                conn,
                "sess_500",
                recent_item_id="88",
                recent_item_recorded_at=two_hours_ago,
            )
            conn.commit()
            conn.close()

            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id="sess_500"
            )
            self.assertIsNone(item_id)
            self.assertIsNone(source)

    def test_TC_get_attribution_failure_degrades_gracefully(self):
        """If session_id is empty or session not found, falls through gracefully."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            seed_item(conn, 77, status="implementing")
            conn.commit()
            conn.close()

            # No session_id -> should still get active_fallback
            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id=""
            )
            self.assertEqual(item_id, "77")
            self.assertEqual(source, "active_fallback")

            # Nonexistent session -> should still get active_fallback
            item_id2, source2 = _resolve_main_session_attribution(
                db_path, project_dir, session_id="nonexistent_sess"
            )
            self.assertEqual(item_id2, "77")
            self.assertEqual(source2, "active_fallback")

    def test_TC_session_current_overrides_active_fallback(self):
        """session_current (Tier 1) takes priority over active_fallback (Tier 2)."""
        from yoke_core.domain.observe import _resolve_main_session_attribution

        with observe_attribution_db() as (db_path, project_dir):
            conn = connect_test_db(db_path)
            # One active item (would match active_fallback)
            seed_item(conn, 77, status="implementing")
            # Session points to a different item
            seed_item(conn, 42, status="idea")
            now = _fresh_now()
            seed_session(
                conn, "sess_600", current_item_id="42", current_item_set_at=now
            )
            conn.commit()
            conn.close()

            item_id, source = _resolve_main_session_attribution(
                db_path, project_dir, session_id="sess_600"
            )
            # session_current should win over active_fallback
            self.assertEqual(item_id, "42")
            self.assertEqual(source, "session_current")


if __name__ == "__main__":
    unittest.main()
