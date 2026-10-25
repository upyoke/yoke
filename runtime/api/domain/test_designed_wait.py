"""The one announcement a deliberately silent wait makes before it starts."""

from __future__ import annotations

import pytest

from yoke_contracts.designed_wait import (
    DESIGNED_WAIT_PREFIX,
    announce_designed_wait,
    designed_wait_line,
    format_duration,
    poll_every,
)


@pytest.mark.parametrize(
    ("seconds", "rendered"),
    [
        (0, "0s"),
        (0.25, "0.25s"),
        (30, "30s"),
        (119.6, "2m"),
        (150, "2m30s"),
        (900, "15m"),
        (3600, "1h"),
        (10800, "3h"),
        (5430, "1h30m30s"),
    ],
)
def test_durations_render_compactly(seconds: float, rendered: str) -> None:
    assert format_duration(seconds) == rendered


def test_a_polling_wait_names_subject_cadence_and_bound() -> None:
    line = designed_wait_line(
        "post-push CI checks on abc123",
        max_wait_seconds=900,
        cadence=poll_every(60),
    )

    assert line == (
        "Waiting by design: post-push CI checks on abc123; checks every 60s; "
        "times out after 15m at most (a limit, not an estimate). "
        "Silence while it waits is expected."
    )


def test_a_blocking_wait_omits_the_cadence() -> None:
    line = designed_wait_line("docker compose to report healthy", max_wait_seconds=120)

    assert line == (
        "Waiting by design: docker compose to report healthy; times out after 2m "
        "at most (a limit, not an estimate). Silence while it waits is expected."
    )


def test_a_wait_with_status_lines_drops_the_silence_promise() -> None:
    line = designed_wait_line(
        "scoped QA",
        max_wait_seconds=1800,
        cadence="checks every 15s; prints a status line every 60s",
        silent=False,
    )

    assert line == (
        "Waiting by design: scoped QA; checks every 15s; prints a status line "
        "every 60s; times out after 30m at most (a limit, not an estimate)."
    )


def test_the_default_sink_is_flushed_stderr(capsys) -> None:
    line = announce_designed_wait("a lock", max_wait_seconds=20)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == line + "\n"
    assert line.startswith(DESIGNED_WAIT_PREFIX)


def test_a_command_sink_receives_the_bare_line(capsys) -> None:
    written: list[str] = []

    line = announce_designed_wait(
        "a lock", max_wait_seconds=20, cadence=poll_every(1), write=written.append
    )

    assert written == [line]
    assert capsys.readouterr().err == ""
