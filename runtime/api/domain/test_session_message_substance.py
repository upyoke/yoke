"""Progress ticks are refused; anything actionable is admitted."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_substance import (
    SUBSTANCE_SCAN_LIMIT_CHARS,
    carries_actionable_signal,
    is_progress_tick,
    validate_body,
)
from yoke_core.domain.session_message_types import SessionMessageError


OBSERVED_PROGRESS_TICKS = (
    "Workflow status: in_progress (elapsed: 480s, next poll: 57s)",
    "# watch_qa_case no progress for 242s; waiting_on=child_process",
    "Still green.",
    "Passing dots at 5%.",
    "Progress dots streaming, no failures so far.",
    "pytest [ 47%] (suppressed 12 ticks)",
    "Workflow status: queued (elapsed: 30s)",
)

# Stop bodies steering-launched workers actually relayed while a gate ran.
# Each was true when written and worthless a minute later.
OBSERVED_STOP_BODIES_WITH_NOTHING_TO_ACT_ON = (
    "Waiting for the run.",
    "I will report when it lands.",
    "I will report when the run exits.",
    "Waiting on the sweep.",
    "Progress digest: still all passes, no failures reported yet.",
    "Verified no stale references to the names this change retired.",
    "Holding until the sweep exits; the background task completion is the "
    "next signal I will act on.",
    "Holding.",
)

SUBSTANTIVE_BODIES = (
    "DONE ALP-1 substantive-only rule landed; merged as abc1234",
    "BLOCKED on ALP-2: its work claim holder has been idle for an hour",
    "QA case failed at 47%: test_send.py::test_refuses_tick FAILED",
    "GO ALP-1: dependency gate cleared; resume the routed leg",
    "Your instruction says merge first, but the queue gate needs the PR open. "
    "Which order do you want?",
    "Found a defect outside my scope: the board renders a stale claim holder.",
    "The migration rehearsal timed out after 900s; the lease is still held.",
    "Should I run the gate against the admin connection?",
)


@pytest.mark.parametrize("body", OBSERVED_PROGRESS_TICKS)
def test_progress_output_is_classified_as_a_tick(body: str) -> None:
    assert is_progress_tick(body) is True


@pytest.mark.parametrize("body", SUBSTANTIVE_BODIES)
def test_actionable_bodies_are_admitted(body: str) -> None:
    assert is_progress_tick(body) is False
    assert carries_actionable_signal(body) is True
    validate_body(body, max_body_bytes=4096)


@pytest.mark.parametrize("body", OBSERVED_STOP_BODIES_WITH_NOTHING_TO_ACT_ON)
def test_a_wait_or_status_body_clears_no_floor(body: str) -> None:
    assert carries_actionable_signal(body) is False


@pytest.mark.parametrize("body", OBSERVED_PROGRESS_TICKS)
def test_a_progress_tick_clears_no_floor(body: str) -> None:
    assert carries_actionable_signal(body) is False


@pytest.mark.parametrize("body", OBSERVED_STOP_BODIES_WITH_NOTHING_TO_ACT_ON)
def test_the_send_path_still_carries_a_deliberate_status_line(body: str) -> None:
    """The floor governs the relay; a sender who chose the words is not refused."""
    assert is_progress_tick(body) is False
    validate_body(body, max_body_bytes=4096)


def test_an_empty_body_clears_no_floor() -> None:
    assert carries_actionable_signal("") is False
    assert carries_actionable_signal("   ") is False


def test_a_long_wait_body_clears_no_floor() -> None:
    """The floor reads what the body names, not how much of it there is."""
    body = "Holding until the sweep exits. " * 20
    assert len(body) > SUBSTANCE_SCAN_LIMIT_CHARS
    assert carries_actionable_signal(body) is False


def test_a_long_body_is_never_a_tick() -> None:
    body = "Still green. " * (SUBSTANCE_SCAN_LIMIT_CHARS // 13 + 1)
    assert len(body) > SUBSTANCE_SCAN_LIMIT_CHARS
    assert is_progress_tick(body) is False


def test_refusal_names_the_reason_and_the_recovery() -> None:
    with pytest.raises(SessionMessageError) as excinfo:
        validate_body("Still green.", max_body_bytes=4096)

    error = excinfo.value
    assert error.code == "body_not_substantive"
    assert "progress output" in str(error)
    assert "your own output" in str(error)


def test_empty_and_oversized_bodies_keep_their_own_refusals() -> None:
    with pytest.raises(SessionMessageError) as empty:
        validate_body("", max_body_bytes=4096)
    assert empty.value.code == "body_empty"

    with pytest.raises(SessionMessageError) as large:
        validate_body("Escalating the blocked item now.", max_body_bytes=4)
    assert large.value.code == "body_too_large"
