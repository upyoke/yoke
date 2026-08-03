"""A gate run records under the authority it bound when it started.

A registered Command case can run for an hour. The stale-session sweep
reclaims on a 20-minute TTL, and an item can be handed off mid-run, so
authority re-derived at recording time answers the wrong question: it
asks who holds the claim now, when what the run earned is the right to
record against the requirement it was admitted for. These cases fix that
boundary and the window that bounds it.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from yoke_core.domain import qa_start_bound_authority as authority
from yoke_core.domain.qa_start_bound_authority import (
    AUTHORITY_WINDOW_SECONDS,
    PAYLOAD_KEY,
    payload_authority,
    payload_grants_authority,
    start_bound_claim_grants,
)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
_SESSION = "s-run"
_ITEM = 1981
_CLAIM = 7695


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(*, session_id=_SESSION, item_id=_ITEM, released_at=None):
    return (session_id, item_id, released_at)


class TestStartBoundClaimGrants(unittest.TestCase):
    def _grants(self, row, **overrides) -> bool:
        kwargs = {"session_id": _SESSION, "item_id": _ITEM, "now": _NOW}
        kwargs.update(overrides)
        with patch.object(authority, "_claim_row", return_value=row):
            return start_bound_claim_grants(_CLAIM, **kwargs)

    def test_live_claim_grants(self):
        self.assertTrue(self._grants(_row()))

    def test_claim_reclaimed_mid_run_still_grants(self):
        # The observed failure: the sweep released the claim while the
        # suite was still running, and the passing run could not record.
        released = _iso(_NOW - timedelta(minutes=40))
        self.assertTrue(self._grants(_row(released_at=released)))

    def test_release_older_than_the_window_does_not_grant(self):
        released = _iso(_NOW - timedelta(seconds=AUTHORITY_WINDOW_SECONDS + 60))
        self.assertFalse(self._grants(_row(released_at=released)))

    def test_window_covers_the_longest_permitted_gate_command(self):
        from yoke_core.domain.qa_constants import MAX_CASE_COMMAND_TIMEOUT_SECONDS

        self.assertEqual(AUTHORITY_WINDOW_SECONDS, MAX_CASE_COMMAND_TIMEOUT_SECONDS)

    def test_another_sessions_claim_never_grants(self):
        self.assertFalse(self._grants(_row(session_id="s-other")))

    def test_a_claim_on_another_item_never_grants(self):
        self.assertFalse(self._grants(_row(item_id=_ITEM + 1)))

    def test_missing_claim_row_does_not_grant(self):
        self.assertFalse(self._grants(None))

    def test_unparseable_release_timestamp_does_not_grant(self):
        self.assertFalse(self._grants(_row(released_at="not-a-timestamp")))

    def test_empty_session_never_grants(self):
        self.assertFalse(self._grants(_row(), session_id=""))


class TestPayloadCarrier(unittest.TestCase):
    def test_case_without_a_bound_claim_carries_nothing(self):
        self.assertEqual(payload_authority({"requirement_id": 1}), {})
        self.assertEqual(payload_authority({PAYLOAD_KEY: None}), {})

    def test_case_with_a_bound_claim_carries_it(self):
        self.assertEqual(
            payload_authority({PAYLOAD_KEY: _CLAIM}), {PAYLOAD_KEY: _CLAIM}
        )

    def test_payload_without_the_key_is_not_authority(self):
        with patch.object(authority, "_claim_row") as claim_row:
            self.assertFalse(
                payload_grants_authority({}, session_id=_SESSION, item_id=_ITEM)
            )
        claim_row.assert_not_called()

    def test_payload_with_the_key_is_checked_against_the_claim(self):
        with patch.object(authority, "_claim_row", return_value=_row()):
            self.assertTrue(
                payload_grants_authority(
                    {PAYLOAD_KEY: _CLAIM}, session_id=_SESSION, item_id=_ITEM
                )
            )


class TestResolveAtStart(unittest.TestCase):
    class _Conn:
        def __init__(self, row):
            self.row = row
            self.params = None

        def execute(self, _sql, params):
            self.params = params
            return self

        def fetchone(self):
            return self.row

    def _resolve(self, row):
        conn = self._Conn(row)
        with patch.object(authority, "_placeholder", return_value="?"):
            resolved = authority.resolve_start_bound_claim_id(
                conn, item_id=_ITEM, session_id=_SESSION
            )
        return resolved, conn

    def test_returns_the_sessions_live_claim(self):
        resolved, conn = self._resolve((_CLAIM,))
        self.assertEqual(resolved, _CLAIM)
        self.assertEqual(conn.params, (_SESSION, _ITEM))

    def test_unclaimed_item_binds_no_authority(self):
        resolved, _ = self._resolve(None)
        self.assertIsNone(resolved)


if __name__ == "__main__":  # pragma: no cover - direct module run
    unittest.main()
