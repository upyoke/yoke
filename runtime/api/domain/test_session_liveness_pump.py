"""A long command keeps its owning session live while it runs.

The stale-session sweep reclaims on a 20-minute TTL, so a gate run that
takes 30-60 minutes has to prove liveness while it waits. These cases fix
the refresh cadence and the failure behavior that make that safe.
"""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from yoke_core.domain import session_liveness_pump
from yoke_core.domain.session_liveness_pump import (
    HEARTBEAT_INTERVAL_SECONDS,
    SessionLivenessPump,
)
from yoke_core.domain.sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES


class _Clock:
    """A hand-advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestRefreshCadence(unittest.TestCase):
    def test_interval_stays_well_inside_the_stale_ttl(self):
        # One dropped refresh must not be enough to make a busy session
        # look reclaimable.
        ttl_seconds = DEFAULT_STALE_THRESHOLD_MINUTES * 60
        self.assertLess(HEARTBEAT_INTERVAL_SECONDS * 2, ttl_seconds)

    def test_no_refresh_before_the_first_interval(self):
        clock = _Clock()
        pump = SessionLivenessPump(session_id="s-1", clock=clock)
        with patch.object(
            session_liveness_pump, "refresh_session_heartbeat", return_value=True
        ) as refresh:
            clock.advance(HEARTBEAT_INTERVAL_SECONDS - 1)
            self.assertFalse(pump.tick())
        refresh.assert_not_called()

    def test_refresh_once_per_interval_not_once_per_tick(self):
        clock = _Clock()
        pump = SessionLivenessPump(session_id="s-1", clock=clock)
        with patch.object(
            session_liveness_pump, "refresh_session_heartbeat", return_value=True
        ) as refresh:
            clock.advance(HEARTBEAT_INTERVAL_SECONDS)
            self.assertTrue(pump.tick())
            for _ in range(500):
                pump.tick()
        self.assertEqual(refresh.call_count, 1)

    def test_waiter_token_travels_with_the_refresh(self):
        clock = _Clock()
        pump = SessionLivenessPump(
            session_id="s-1",
            background_waiter_id="wait-1",
            clock=clock,
        )
        with patch.object(
            session_liveness_pump, "refresh_session_heartbeat", return_value=True
        ) as refresh:
            clock.advance(HEARTBEAT_INTERVAL_SECONDS)
            self.assertTrue(pump.tick())

        refresh.assert_called_once_with(
            "s-1",
            background_waiter_id="wait-1",
        )

    def test_hour_long_run_refreshes_throughout(self):
        # The regression shape: a 60-minute gate with an idle session. The
        # session must be refreshed the whole way, not just at the start.
        clock = _Clock()
        pump = SessionLivenessPump(session_id="s-1", clock=clock)
        with patch.object(
            session_liveness_pump, "refresh_session_heartbeat", return_value=True
        ) as refresh:
            for _ in range(3600):
                clock.advance(1.0)
                pump.tick()
        expected = int(3600 // HEARTBEAT_INTERVAL_SECONDS)
        self.assertEqual(refresh.call_count, expected)


class TestIdentityResolution(unittest.TestCase):
    def test_ambient_identity_uses_the_canonical_no_argument_resolver(self):
        with patch(
            "yoke_core.domain.session_ambient_identity.resolve_ambient_session_id",
            return_value="s-canonical",
        ):
            self.assertEqual(session_liveness_pump._ambient_session_id(), "s-canonical")

    def test_ambient_identity_is_resolved_only_when_a_refresh_is_due(self):
        clock = _Clock()
        pump = SessionLivenessPump(clock=clock)
        with patch.object(
            session_liveness_pump, "_ambient_session_id", return_value="s-9"
        ) as ambient:
            pump.tick()
            ambient.assert_not_called()
            clock.advance(HEARTBEAT_INTERVAL_SECONDS)
            with patch.object(
                session_liveness_pump, "refresh_session_heartbeat", return_value=True
            ):
                self.assertTrue(pump.tick())
            self.assertEqual(ambient.call_count, 1)

    def test_a_process_with_no_session_stays_inert(self):
        clock = _Clock()
        pump = SessionLivenessPump(clock=clock)
        with (
            patch.object(
                session_liveness_pump, "_ambient_session_id", return_value=""
            ) as ambient,
            patch.object(session_liveness_pump, "refresh_session_heartbeat") as refresh,
        ):
            for _ in range(5):
                clock.advance(HEARTBEAT_INTERVAL_SECONDS)
                self.assertFalse(pump.tick())
        self.assertEqual(ambient.call_count, 1)
        refresh.assert_not_called()


class TestRefreshFailureIsNotFatal(unittest.TestCase):
    def test_waiter_refresh_sends_a_token_bound_pulse(self):
        captured = {}

        class Response:
            success = True

        def dispatch(**kwargs):
            captured.update(kwargs)
            return Response()

        with patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            dispatch,
        ):
            self.assertTrue(
                session_liveness_pump.refresh_session_heartbeat(
                    "s-1",
                    background_waiter_id="wait-1",
                )
            )

        self.assertEqual(
            captured["payload"],
            {
                "background_waiter": {
                    "action": "pulse",
                    "waiter_id": "wait-1",
                }
            },
        )

    def test_a_transport_failure_does_not_interrupt_the_command(self):
        # The command being watched is the caller's real work; a heartbeat
        # that cannot land must never take it down.
        def _explode(*_args, **_kwargs):
            raise RuntimeError("server unreachable")

        with patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            _explode,
        ):
            self.assertFalse(session_liveness_pump.refresh_session_heartbeat("s-1"))


class TestWaitCadence(unittest.TestCase):
    def test_a_long_wait_is_split_at_the_refresh_interval(self):
        clock = _Clock()
        sleeps: list[float] = []
        pump = SessionLivenessPump(session_id="s-1", clock=clock)

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.advance(seconds)

        with patch.object(
            session_liveness_pump, "refresh_session_heartbeat", return_value=True
        ) as refresh:
            pump.wait(HEARTBEAT_INTERVAL_SECONDS * 2.5, sleep=sleep)

        self.assertEqual(
            sleeps,
            [
                HEARTBEAT_INTERVAL_SECONDS,
                HEARTBEAT_INTERVAL_SECONDS,
                HEARTBEAT_INTERVAL_SECONDS / 2,
            ],
        )
        self.assertEqual(refresh.call_count, 2)

    def test_a_blocking_scope_refreshes_in_the_background(self):
        pump = SessionLivenessPump(session_id="s-1", interval_seconds=0.01)
        refreshed = threading.Event()

        def record_refresh(*_args, **_kwargs) -> bool:
            refreshed.set()
            return True

        with patch.object(
            session_liveness_pump,
            "refresh_session_heartbeat",
            side_effect=record_refresh,
        ) as refresh_call:
            with pump.running():
                self.assertTrue(
                    refreshed.wait(timeout=5),
                    "background refresh did not arrive inside the load-tolerant window",
                )

        self.assertGreaterEqual(refresh_call.call_count, 1)


if __name__ == "__main__":  # pragma: no cover - direct module run
    unittest.main()
