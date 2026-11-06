"""Tests: ``events list --current-episode`` boundary filtering.

Covers the explicit session filter requirement, fail-closed
empty-set behavior when no boundary is recorded, AND-composition with
other filters, and boundary resolution against
``harness_sessions.episode_started_at`` (the events-side filtering of
telemetry rows stays; only boundary RESOLUTION reads the session
column).
"""

from __future__ import annotations

from runtime.api.domain.events_queries_current_episode_test_support import (
    _SCHEMA as _SCHEMA,
    _apply_events_schema as _apply_events_schema,
    _insert_event as _insert_event,
    _setup_db as _setup_db,
    _stamp_episode as _stamp_episode,
)


import unittest

# Load events_crud first so the events_queries <-> events_crud circular
# import resolves the normal way (events_crud completes its module-level
# definitions, then pulls events_queries; the reverse order fails when
# events_queries reaches its events_crud import and events_crud tries
# to re-enter the partially-initialized module).
import yoke_core.domain.events_crud  # noqa: F401
from yoke_core.domain.events_queries import _build_where, cmd_list


class TestCurrentEpisodeFlag(unittest.TestCase):
    def test_requires_explicit_session_id(self) -> None:
        with self.assertRaises(ValueError) as exc:
            _build_where(["--current-episode"])
        self.assertIn("--session-id", str(exc.exception))

    def test_returns_empty_set_when_no_boundary_recorded(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="SomethingElse",
                session_id="sess-x",
                created_at="2026-05-01T00:00:00Z",
            )
            # No harness_sessions row / no episode_started_at: fail closed.
            result = cmd_list(
                db_path,
                ["--session-id", "sess-x", "--current-episode"],
            )
            self.assertEqual(result, "")

    def test_boundary_started_only(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="UnrelatedEvent",
                session_id="sess-a",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-a",
                created_at="2026-05-02T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-a",
                created_at="2026-05-03T00:00:00Z",
            )
            _stamp_episode(db_path, "sess-a", "2026-05-02T00:00:00Z")
            result = cmd_list(
                db_path,
                ["--session-id", "sess-a", "--current-episode"],
            )
            self.assertIn("HarnessSessionStarted", result)
            self.assertIn("WorkClaimed", result)
            self.assertNotIn("UnrelatedEvent", result)

    def test_boundary_prefers_resumed_over_started(self) -> None:
        """The stamped column carries the most recent boundary moment."""
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-b",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-b",
                created_at="2026-05-02T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="HarnessSessionResumed",
                session_id="sess-b",
                created_at="2026-05-03T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="EpisodeTwoEvent",
                session_id="sess-b",
                created_at="2026-05-04T00:00:00Z",
            )
            # register_session stamped the boundary at the resume moment.
            _stamp_episode(db_path, "sess-b", "2026-05-03T00:00:00Z")
            result = cmd_list(
                db_path,
                ["--session-id", "sess-b", "--current-episode"],
            )
            self.assertIn("HarnessSessionResumed", result)
            self.assertIn("EpisodeTwoEvent", result)
            self.assertNotIn("WorkClaimed", result)

    def test_other_session_events_not_returned(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-c",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="OtherSessionEvent",
                session_id="sess-other",
                created_at="2026-05-02T00:00:00Z",
            )
            _stamp_episode(db_path, "sess-c", "2026-05-01T00:00:00Z")
            result = cmd_list(
                db_path,
                ["--session-id", "sess-c", "--current-episode"],
            )
            self.assertNotIn("OtherSessionEvent", result)

    def test_composes_with_event_name_filter(self) -> None:
        """Filter composition is AND across all predicates."""
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-d",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-d",
                created_at="2026-05-02T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkReleased",
                session_id="sess-d",
                created_at="2026-05-03T00:00:00Z",
            )
            _stamp_episode(db_path, "sess-d", "2026-05-01T00:00:00Z")
            result = cmd_list(
                db_path,
                [
                    "--session-id",
                    "sess-d",
                    "--current-episode",
                    "--event-name",
                    "WorkClaimed",
                ],
            )
            self.assertIn("WorkClaimed", result)
            self.assertNotIn("WorkReleased", result)
            self.assertNotIn("HarnessSessionStarted", result)


if __name__ == "__main__":
    unittest.main()
