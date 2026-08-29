"""Progress ticks are refused; anything actionable is admitted."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_substance import (
    SUBSTANCE_SCAN_LIMIT_CHARS,
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

SUBSTANTIVE_BODIES = (
    "DONE ALP-1 substantive-only rule landed; merged as abc1234",
    "BLOCKED on ALP-2: its work claim holder has been idle for an hour",
    "QA case failed at 47%: test_send.py::test_refuses_tick FAILED",
    "GO ALP-1: dependency gate cleared; resume the routed leg",
    "Your instruction says merge first, but the queue gate needs the PR open. "
    "Which order do you want?",
    "Found a defect outside my scope: the board renders a stale claim holder.",
    "The migration rehearsal timed out after 900s; the lease is still held.",
)


@pytest.mark.parametrize("body", OBSERVED_PROGRESS_TICKS)
def test_progress_output_is_classified_as_a_tick(body: str) -> None:
    assert is_progress_tick(body) is True


@pytest.mark.parametrize("body", SUBSTANTIVE_BODIES)
def test_actionable_bodies_are_admitted(body: str) -> None:
    assert is_progress_tick(body) is False
    validate_body(body, max_body_bytes=4096)


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
