"""Detailed result capture is gated on a live bounded debug campaign.

``YokeFunctionCalled`` is compact on every routine call. The one way the
full result rides it again is a scoped, expiring, record-capped campaign
owned by :mod:`yoke_core.api.observability_debug`. These tests pin the
five answers that gate says: default off, armed and in scope, expired,
out of scope, and record cap exhausted.

The campaign environment is set whole on every dispatch — all three
variables, empty when unarmed — so an ambient campaign on the machine
running these tests can neither arm nor disarm a case.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

from yoke_core.api.observability_debug import (
    DEBUG_MAX_RECORDS_ENV,
    DEBUG_SCOPE_ENV,
    DEBUG_UNTIL_ENV,
    reset_debug_state,
)
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import register

from runtime.api.domain.test_yoke_function_dispatch import (
    _Req,
    _Resp,
    _make_request,
    _stable_kwargs,
)
from runtime.api.domain.test_yoke_function_dispatch_compact_events import (
    _BIG_RESULT,
    CompactEventBase,
    _big_result_handler,
)


def _campaign_env(scope: str = "", *, hours: float = 1.0,
                  max_records: str = "") -> Dict[str, str]:
    """A complete campaign environment; empty values mean no campaign."""
    until = ""
    if scope:
        until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    return {
        DEBUG_SCOPE_ENV: scope,
        DEBUG_UNTIL_ENV: until,
        DEBUG_MAX_RECORDS_ENV: max_records,
    }


class TestDetailedCaptureIsCampaignGated(CompactEventBase):
    """The full result rides the event only under a live, in-scope campaign."""

    def setUp(self) -> None:
        super().setUp()
        reset_debug_state()

    def tearDown(self) -> None:
        reset_debug_state()
        super().tearDown()

    def _dispatch_under(self, env: Dict[str, str]) -> Dict[str, Any]:
        register(
            "capture.family.op", _big_result_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        with patch.dict(os.environ, env, clear=False):
            dispatch(_make_request("capture.family.op"))
        return self._called_context()

    def test_no_campaign_keeps_the_event_compact(self):
        self.assertNotIn("result", self._dispatch_under(_campaign_env()))

    def test_matching_function_campaign_carries_the_full_result(self):
        ctx = self._dispatch_under(_campaign_env("function:capture.family.op"))
        self.assertEqual(ctx["result"], _BIG_RESULT)
        # The compact scalars stay beside it, so an audit keyed on them
        # reads the same whether or not a campaign was live.
        self.assertGreater(ctx["result_byte_count"], 19_000)
        self.assertEqual(len(ctx["result_checksum"]), 64)

    def test_matching_session_campaign_carries_the_full_result(self):
        ctx = self._dispatch_under(_campaign_env("session:s-1"))
        self.assertEqual(ctx["result"], _BIG_RESULT)

    def test_expired_campaign_keeps_the_event_compact(self):
        ctx = self._dispatch_under(
            _campaign_env("function:capture.family.op", hours=-1.0)
        )
        self.assertNotIn("result", ctx)

    def test_out_of_scope_campaign_keeps_the_event_compact(self):
        ctx = self._dispatch_under(_campaign_env("function:some.other.op"))
        self.assertNotIn("result", ctx)

    def test_exhausted_record_cap_keeps_the_event_compact(self):
        register(
            "capture.capped.op", _big_result_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        env = _campaign_env("function:capture.capped.op", max_records="1")
        with patch.dict(os.environ, env, clear=False):
            dispatch(_make_request("capture.capped.op"))
            dispatch(_make_request("capture.capped.op"))

        calls = events_module.emit_event.calls  # type: ignore[attr-defined]
        contexts = [c["kwargs"]["context"] for c in calls
                    if c["args"] and c["args"][0] == "YokeFunctionCalled"]
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0]["result"], _BIG_RESULT)
        self.assertNotIn("result", contexts[1])


if __name__ == "__main__":  # pragma: no cover - direct invocation
    unittest.main()
