"""Regression: ``release_all_claims`` clears ``current_item_id``.

Parity with the typed per-claim release path: bulk-releasing every
claim a session holds must also clear ``current_item_id`` so the
path-claim pre-edit guard cannot read a dangling focus link after the
HTTP ``POST /sessions/{id}/release-all`` endpoint (or any direct caller
that does not also end the session).
"""

from __future__ import annotations

from runtime.api.test_sessions import _register, conn  # noqa: F401  (pytest fixture)
from yoke_core.domain.sessions import claim_work, release_all_claims


def test_release_all_clears_current_item_id(conn):
    _register(conn)
    claim_work(conn, session_id="sess-1", item_id="YOK-1")
    claim_work(conn, session_id="sess-1", item_id="YOK-2")

    before = conn.execute(
        "SELECT current_item_id FROM harness_sessions WHERE session_id='sess-1'"
    ).fetchone()
    assert before["current_item_id"] is not None

    release_all_claims(conn, "sess-1", reason="released")

    after = conn.execute(
        "SELECT current_item_id, recent_item_id FROM harness_sessions "
        "WHERE session_id='sess-1'"
    ).fetchone()
    assert after["current_item_id"] is None
    # The cleared focus is preserved on recent_item_id (matches the
    # canonical _maybe_clear_current_item behaviour).
    assert after["recent_item_id"] == before["current_item_id"]
