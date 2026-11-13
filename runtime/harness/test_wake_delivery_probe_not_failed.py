"""A subagent's declined hook defers delivery; it is not a failed attempt.

Note 94880: a receipt read "never injected, last attempt failed
(probe_subagent_exit x2)" seconds before its parent injected it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.session_control.wake_delivery import (
    HOOK_DEFERRED_FOR_BUDGET_RESULT,
    HOOK_DEFERRED_RESULTS,
    HOOK_SUBAGENT_EXIT_RESULT,
    delivery_attempt_diagnostic,
    delivery_attempt_failed,
)
from yoke_core.domain.session_message_delivery_probe import (
    PROBE_LEASE_FAILED,
    PROBE_SUBAGENT_EXIT,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    delivery_state,
)


def test_subagent_exit_probe_is_a_deferral_not_a_failure() -> None:
    assert PROBE_SUBAGENT_EXIT == HOOK_SUBAGENT_EXIT_RESULT
    assert HOOK_DEFERRED_RESULTS == {
        HOOK_DEFERRED_FOR_BUDGET_RESULT,
        HOOK_SUBAGENT_EXIT_RESULT,
    }
    assert delivery_attempt_failed(PROBE_SUBAGENT_EXIT) is False
    assert delivery_attempt_diagnostic(PROBE_SUBAGENT_EXIT, {}) == ""


def test_other_probe_reasons_still_fail() -> None:
    assert delivery_attempt_failed(PROBE_LEASE_FAILED) is True


def _state(result_code: str, failed_count: int) -> str:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    return delivery_state(
        {"session_id": "parent", "terminated_at": None, "ended_at": None},
        result_code=result_code,
        sent_at=now - timedelta(seconds=30),
        grace=timedelta(seconds=60),
        sla=timedelta(seconds=120),
        current=now,
        failed_count=failed_count,
    )


def test_subagent_exit_probe_does_not_report_attempt_failed() -> None:
    assert _state(PROBE_SUBAGENT_EXIT, 0) != ATTEMPT_FAILED
    assert _state(PROBE_LEASE_FAILED, 0) == ATTEMPT_FAILED
