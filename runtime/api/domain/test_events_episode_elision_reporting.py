"""Tests: an empty ``--current-episode`` answer says what it hid.

Sibling of ``test_events_queries_current_episode``, which pins the
boundary filter itself. The fixtures are shared from there so both
suites describe the same events table.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.events_current_episode import (
    note_elided_prior_episodes,
)
from yoke_core.domain.events_queries import _build_where
from runtime.api.domain.test_events_queries_current_episode import (
    _insert_event,
    _setup_db,
    _stamp_episode,
)


class TestElidedPriorEpisodesAreReported(unittest.TestCase):
    """An empty current episode must not read as "nothing happened".

    A session that crosses a transient end/resume mid-work keeps its
    earlier evidence in the prior episode. The observed harm: a close-out
    asked for this episode's guardrail denials four minutes after a
    sleep/resume cycle opened a new one, got nothing back, and reported a
    clean run over seventeen real denials.
    """

    def _note(self, db_path, args, payload):
        where, params = _build_where(args, db_path=db_path)
        result: dict = {"rows": []}
        note_elided_prior_episodes(
            payload, where, params, result, db_path=db_path,
        )
        return result

    def test_rows_before_the_boundary_are_counted(self) -> None:
        with _setup_db() as db_path:
            for stamp in ("2026-05-01T00:00:00Z", "2026-05-01T01:00:00Z"):
                _insert_event(
                    db_path,
                    name="HarnessToolCallDenied",
                    session_id="sess-e",
                    created_at=stamp,
                )
            _stamp_episode(db_path, "sess-e", "2026-05-02T00:00:00Z")
            result = self._note(
                db_path,
                ["--session-id", "sess-e", "--current-episode"],
                {"current_episode": True, "session_id": "sess-e"},
            )
            self.assertEqual(result["elided_prior_episode_rows"], 2)

    def test_a_genuinely_quiet_episode_stays_quiet(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-f",
                created_at="2026-05-02T01:00:00Z",
            )
            _stamp_episode(db_path, "sess-f", "2026-05-02T00:00:00Z")
            result = self._note(
                db_path,
                ["--session-id", "sess-f", "--current-episode"],
                {"current_episode": True, "session_id": "sess-f"},
            )
            self.assertNotIn("elided_prior_episode_rows", result)

    def test_an_unresolved_boundary_reports_everything_it_hid(self) -> None:
        """Failing closed is right; failing closed in silence is not."""
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessToolCallDenied",
                session_id="sess-g",
                created_at="2026-05-01T00:00:00Z",
            )
            result = self._note(
                db_path,
                ["--session-id", "sess-g", "--current-episode"],
                {"current_episode": True, "session_id": "sess-g"},
            )
            self.assertEqual(result["elided_prior_episode_rows"], 1)

    def test_the_count_honours_every_other_filter(self) -> None:
        with _setup_db() as db_path:
            for name in ("HarnessToolCallDenied", "WorkClaimed"):
                _insert_event(
                    db_path,
                    name=name,
                    session_id="sess-h",
                    created_at="2026-05-01T00:00:00Z",
                )
            _stamp_episode(db_path, "sess-h", "2026-05-02T00:00:00Z")
            result = self._note(
                db_path,
                [
                    "--session-id", "sess-h",
                    "--current-episode",
                    "--event-name", "HarnessToolCallDenied",
                ],
                {"current_episode": True, "session_id": "sess-h"},
            )
            self.assertEqual(result["elided_prior_episode_rows"], 1)

    def test_no_episode_flag_means_no_annotation(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessToolCallDenied",
                session_id="sess-i",
                created_at="2026-05-01T00:00:00Z",
            )
            result = self._note(
                db_path, ["--session-id", "sess-i"], {"session_id": "sess-i"},
            )
            self.assertNotIn("elided_prior_episode_rows", result)


if __name__ == "__main__":
    unittest.main()
