"""GitHub polling loops: refused, with no override offered or honoured."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_constants import SUPPRESSION_TOKEN
from yoke_core.domain.lint_long_command_polling_decide import (
    _format_sleep_reason,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
    _non_bash_payload,
)


@pytest.fixture(autouse=True)
def _deny_mode():
    with mock.patch.object(lint, "_read_lint_mode", return_value="deny"):
        yield


@pytest.mark.parametrize(
    "command",
    [
        "until gh api repos/acme/w/actions/runs/1 --jq .status | grep -q "
        "completed; do sleep 60; done",
        "while true; do gh run view 1 --json status; sleep 60; done",
        "while sleep 90; do gh run view 1 --repo acme/w; done",
        f"until gh api repos/acme/w/actions/runs/1; do sleep 60; done  "
        f"{SUPPRESSION_TOKEN}",
    ],
)
def test_github_poll_loop_is_denied_without_an_override(command: str) -> None:
    result = lint.evaluate_payload(_bash_payload(command))

    assert result is not None
    verdict, reason, _ctx = result
    assert verdict == "deny"
    assert reason.startswith("DENIED: shell loop polling GitHub")
    assert "End the turn; the verdict wakes you" in reason
    assert "yoke watch ci-run -- REF" in reason
    assert "lint:" not in reason


@pytest.mark.parametrize(
    "command",
    [
        "gh run view 1 --repo acme/w --json status,conclusion",
        "gh api repos/acme/w/actions/runs/1",
        "until curl -fs https://example.test/health; do sleep 60; done",
        'while read -r line; do echo "$line"; done < notes.txt',
    ],
)
def test_single_reads_and_other_loops_pass(command: str) -> None:
    assert lint.evaluate_payload(_bash_payload(command)) is None


def test_non_bash_tool_is_not_a_poll_loop() -> None:
    payload = _non_bash_payload(
        "Edit", tool_input={"command": "until gh api x; do sleep 60; done"}
    )
    assert lint.evaluate_payload(payload) is None


def test_sleep_refusal_offers_no_override() -> None:
    assert SUPPRESSION_TOKEN not in _format_sleep_reason(10, "deny")
