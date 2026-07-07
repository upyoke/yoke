"""Resume-block render-once cycle on ``pending_resume_notice``.

Split sibling of :mod:`test_sessions_lifecycle_reacquire_conflict`
(350-line authored cap): write at reactivation -> lookup -> render ->
clear, plus the advisory-only marker semantics.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain.sessions_lifecycle_reactivation import (
    emit_reactivated_with_released_claims,
)
from runtime.api.test_sessions_lifecycle_reacquire_conflict import (
    _PgReacquireTestCase,
    _insert_released_claim,
    _insert_session,
    _iso,
)


class TestResumeBlockNoticeRendering(_PgReacquireTestCase):
    def test_render_lines_read_notice_payload(self) -> None:
        from yoke_core.domain.sessions_resume_block import render_resume_block_lines

        notice = {
            "released_claims": [{"target_kind": "item", "item_id": 17}],
            "reacquired_count": 1,
            "conflict_count": 1,
        }
        lines = render_resume_block_lines(notice)
        rendered = "\n".join(lines)
        self.assertIn("YOK-17 (item)", rendered)
        self.assertIn("1 auto-reacquired", rendered)
        self.assertIn("1 NOT auto-reacquired", rendered)

    def test_conflict_only_notice_is_advisory_marker_and_clears(self) -> None:
        from yoke_core.domain.sessions_resume_block import render_and_mark
        from yoke_core.domain.sessions_resume_notice import (
            lookup_unacknowledged_resume_block,
        )

        conn = self.conn
        _insert_session(conn, "sess-r")
        notice = json.dumps({
            "reactivated_at": _iso(),
            "released_claims": [{"target_kind": "item", "item_id": 18}],
            "reacquired_count": 0,
            "conflict_count": 1,
        })
        conn.execute(
            "UPDATE harness_sessions SET pending_resume_notice = %s "
            "WHERE session_id = 'sess-r'",
            (notice,),
        )
        conn.commit()
        with mock.patch(
            "yoke_core.domain.sessions_resume_block."
            "emit_harness_session_resume_block_shown",
        ) as marker:
            block = render_and_mark(
                conn, "sess-r", harness_event="UserPromptSubmit",
            )
        self.assertIn("YOK-18 (item)", block)
        kwargs = marker.call_args.kwargs
        self.assertFalse(kwargs["reacquired"])
        self.assertTrue(kwargs["advisory_only"])
        # Render-once: the notice clears; a second render is empty.
        self.assertIsNone(
            lookup_unacknowledged_resume_block(conn, "sess-r")
        )
        with mock.patch(
            "yoke_core.domain.sessions_resume_block."
            "emit_harness_session_resume_block_shown",
        ):
            self.assertEqual(
                render_and_mark(
                    conn, "sess-r", harness_event="UserPromptSubmit",
                ),
                "",
            )

    def test_reactivation_writes_pending_notice(self) -> None:
        from yoke_core.domain.sessions_resume_notice import (
            lookup_unacknowledged_resume_block,
        )

        conn = self.conn
        _insert_session(conn, "sess-w")
        _insert_released_claim(conn, "sess-w", 700, released_age_s=10)
        with mock.patch(
            "yoke_core.domain.events.emit_event"
        ), mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ):
            emit_reactivated_with_released_claims(
                conn, "sess-w", reacquire_window_s=300,
            )
        notice = lookup_unacknowledged_resume_block(conn, "sess-w")
        self.assertIsNotNone(notice)
        self.assertEqual(
            notice["released_claims"],
            [{"target_kind": "item", "item_id": 700}],
        )
        self.assertEqual(notice["reacquired_count"], 1)
        self.assertEqual(notice["conflict_count"], 0)
        self.assertTrue(notice["reactivated_at"])


if __name__ == "__main__":
    unittest.main()
