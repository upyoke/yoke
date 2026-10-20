"""Ordinary reads pass; short waits require session-owned capture evidence."""

from unittest import mock

import pytest

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    FINISHED,
    RUNNING,
    _bash_payload,
)


@pytest.fixture(autouse=True)
def capture_history():
    with (
        mock.patch.object(lint, "_read_lint_mode", return_value="deny"),
        mock.patch.object(lint, "_db_available", return_value=True),
        mock.patch.object(lint, "_recent_bash_commands") as recent,
    ):
        recent.return_value = [("owner", None, "check > /tmp/run.log")]
        yield recent


@pytest.mark.parametrize("state", [FINISHED, RUNNING])
@pytest.mark.parametrize(
    "target", ["/tmp/run.log", "/tmp/note.json", "/private/tmp/tasks/job.output"]
)
def test_repeated_reads_need_no_sentinel_or_suppression(state, target, capture_history):
    capture_history.return_value += [("read", None, f"cat {target}")]
    for _ in range(3):
        assert (
            lint.evaluate_payload(
                _bash_payload(f"cat {target}", captures={target: state})
            )
            is None
        )
    capture_history.assert_not_called()


@pytest.mark.parametrize(
    "owner",
    [
        "check > /tmp/run.log",
        "yoke watch pytest --raw-capture /tmp/run.log",
        "yoke watch pytest --progress-capture=/tmp/run.log",
    ],
)
@pytest.mark.parametrize("separator", [";", "&&"])
def test_short_sleep_before_registered_capture_read_refuses(
    owner, separator, capture_history
):
    capture_history.return_value = [("owner", None, owner)]
    result = lint.evaluate_payload(
        _bash_payload(f"sleep 2 {separator} tail -80 /tmp/run.log")
    )
    assert result is not None
    assert result[0] == "deny"
    assert result[2]["capture_file"] == "/tmp/run.log"


@pytest.mark.parametrize(
    "command",
    [
        "server & sleep 2; curl https://example.test/health",
        "sleep 2; cat /tmp/note.json",
        "cat /tmp/run.log; sleep 2; cat /tmp/note.json",
        "check > /tmp/run.log; tail -80 /tmp/run.log",
        "sleep 60; tail -80 /tmp/run.log",
    ],
)
def test_startup_waits_unregistered_reads_and_foreground_redirects_pass(command):
    assert lint.evaluate_payload(_bash_payload(command)) is None


def test_missing_registration_evidence_does_not_infer_capture():
    with mock.patch.object(lint, "_db_available", return_value=False):
        assert lint.evaluate_payload(_bash_payload("sleep 2; cat /tmp/run.log")) is None


def test_capture_registration_is_scoped_to_current_session(capture_history):
    capture_history.return_value = []
    assert (
        lint.evaluate_payload(
            _bash_payload("sleep 2; cat /tmp/run.log", session_id="other")
        )
        is None
    )
    capture_history.assert_called_once_with("", "other")
