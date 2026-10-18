"""Long credential-local host phases heartbeat and print watcher progress."""

from __future__ import annotations

import json
import threading

import pytest

from yoke_core.domain.machine_qa_phase_heartbeat import heartbeat_during
from yoke_core.domain.qa_plan_execution_checkin import QaPlanCommunicationUnknown
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_qa_plan import classify_qa_plan_line


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_blocking_phase_beats_and_prints_until_it_finishes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    beats: list[bool] = []
    third_beat = threading.Event()

    def beat() -> None:
        beats.append(True)
        if len(beats) == 3:
            third_beat.set()

    with heartbeat_during("starting_state_restore", beat, interval_seconds=0.01):
        assert third_beat.wait(5), "the phase never heartbeated three times"
    count = len(beats)

    lines = _lines(capsys)
    assert count >= 3
    assert len(lines) == count
    assert {line["event"] for line in lines} == {"machine_qa.heartbeat"}
    assert {line["phase"] for line in lines} == {"starting_state_restore"}


def test_heartbeat_line_counts_as_plan_watcher_progress(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with heartbeat_during("fixture_cleanup", None):
        pass

    printed = capsys.readouterr().out.splitlines()
    assert printed
    assert classify_qa_plan_line(printed[0]).cls is LineClass.PROGRESS


def test_failed_heartbeat_is_named_and_the_phase_still_finishes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    finished: list[bool] = []

    def beat() -> None:
        raise RuntimeError("relay refused")

    with heartbeat_during("fixture_cleanup", beat, interval_seconds=0.01):
        finished.append(True)

    assert finished == [True]
    failure = _lines(capsys)[-1]
    assert failure["error_code"] == "machine_qa_heartbeat_failed"
    assert failure["diagnostic"] == "RuntimeError: relay refused"
    assert "yoke qa plan run" in str(failure["recovery"])


def test_unknown_heartbeat_delivery_is_raised_after_the_phase(
    capsys: pytest.CaptureFixture[str],
) -> None:
    finished: list[bool] = []

    def beat() -> None:
        raise QaPlanCommunicationUnknown(
            function_id="qa.plan_execution.heartbeat", request_id="r-1", attempts=1
        )

    with pytest.raises(QaPlanCommunicationUnknown):
        with heartbeat_during("starting_state_reset", beat, interval_seconds=0.01):
            finished.append(True)

    assert finished == [True]
    capsys.readouterr()
