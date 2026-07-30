"""The per-project-windowed sessions roster read.

``sessions.list`` with ``per_project=True`` gives each project its own
newest-:data:`PER_PROJECT_SESSIONS_LIST_CAP` slice so a busy project cannot
crowd a quiet one out of the fetch window. Shares the row-insert helpers with
:mod:`runtime.api.domain.handlers.test_sessions_list_handler`.
"""

from __future__ import annotations

from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.sessions_list_read import (
    PER_PROJECT_SESSIONS_LIST_CAP,
    list_sessions,
)

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _insert_session,
    _iso,
    _request,
)


class TestPerProjectWindow:
    def test_windowed_roster_caps_per_project_and_keeps_quiet(self, test_db):
        cap = PER_PROJECT_SESSIONS_LIST_CAP
        test_db.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (77, "quiet", "Quiet", _iso()),
        )
        test_db.commit()
        # A busy project fills more than a per-project slice, all newer than
        # the quiet project's lone session.
        for index in range(cap + 2):
            _insert_session(test_db, f"busy-{index}", last_heartbeat=_iso(index))
        _insert_session(test_db, "quiet-1", last_heartbeat=_iso(1000), project_id=77)

        # Flat unscoped read (newest-N across the universe) crowds the quiet
        # project's lone session out entirely.
        flat = {row["session_id"] for row in list_sessions(limit=cap)}
        assert "quiet-1" not in flat
        assert len(flat) == cap

        # The per-project windowed roster caps the busy project and keeps the
        # quiet project's session in its own partition.
        windowed = list_sessions(per_project=True)
        busy_rows = [row for row in windowed if row["project_id"] == 1]
        assert len(busy_rows) == cap
        assert any(row["session_id"] == "quiet-1" for row in windowed)

    def test_handler_rejects_non_boolean_per_project(self, test_db):
        outcome = handle_sessions_list(_request({"per_project": "yes"}))
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
