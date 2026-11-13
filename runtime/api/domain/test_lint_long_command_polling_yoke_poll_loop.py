"""Sleep loops around Yoke reads: refused with the park recovery."""

from __future__ import annotations

import pytest

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling import (
    _build_context_from_payload,
    evaluate,
)
from yoke_core.domain.lint_long_command_polling_constants import SUPPRESSION_TOKEN
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
    _non_bash_payload,
)
from yoke_core.hooks.types import Outcome

# The loops from notes 95012 and 95309 (PLAT-400 and PLAT-407 workers).
MESSAGES_LOOP = (
    "until yoke messages list --unread | grep -q 'QA ready'; do sleep 20; done"
)
ITEM_STATE_LOOP = (
    'until s=$(yoke items get PLAT-407 status); [ "$s" = "status: done" ]; '
    "do sleep 300; done"
)


@pytest.mark.parametrize(
    "command",
    [
        MESSAGES_LOOP,
        ITEM_STATE_LOOP,
        "while true; do yoke db read 'SELECT 1'; sleep 60; done",
        "while sleep 30; do yoke items get YOK-1 status; done",
        f"bash -c {MESSAGES_LOOP!r}",
        f"{MESSAGES_LOOP}  {SUPPRESSION_TOKEN}",
    ],
)
def test_yoke_read_poll_loop_is_denied_with_park_recovery(command: str) -> None:
    result = lint.evaluate_payload(_bash_payload(command))

    assert result is not None
    reason, _ctx = result
    assert reason.startswith("DENIED: shell loop polling Yoke")
    assert "yoke sessions touch --mode parked" in reason
    assert "--print-streaming-pair" in reason
    assert "yoke watch ci-run" not in reason


@pytest.mark.parametrize(
    "command",
    [
        "until yoke items update YOK-1 --status done; do sleep 5; done",
        "yoke messages list --unread",
        "until yoke messages list; do echo retry; done",
        "while true; do echo 'yoke items get X; sleep 10'; done",
    ],
)
def test_yoke_writes_single_reads_and_quoted_loops_pass(command: str) -> None:
    assert lint.evaluate_payload(_bash_payload(command)) is None


def test_monitor_loop_around_yoke_is_allowed() -> None:
    payload = _non_bash_payload("Monitor", tool_input={"command": MESSAGES_LOOP})
    decision = evaluate(_build_context_from_payload(payload))
    assert decision.outcome is Outcome.NOOP


def test_github_loop_keeps_the_ci_reason() -> None:
    result = lint.evaluate_payload(
        _bash_payload("until s=$(gh api repos/a/b/actions/runs/1); do sleep 60; done")
    )
    assert result is not None
    assert result[0].startswith("DENIED: shell loop polling GitHub")
