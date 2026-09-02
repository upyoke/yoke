"""Tests for progress batching: the digest and its flush window.

Unit cases exercise :class:`ProgressDigest` and the shared
``--flush-seconds`` option directly; runner cases drive
:func:`yoke_core.tools._watch_runner.run_watcher` against synthetic
streams to prove the three flush points — the window timer, an urgent
line, and completion.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from yoke_core.tools import _watch_digest, _watch_runner, watch_deploy
from yoke_core.tools._watch_digest import (
    DEFAULT_FLUSH_SECONDS,
    DIGEST_SEPARATOR,
    ProgressDigest,
)


class _FakeClock:
    """Monotonic clock fake whose value the test advances explicitly."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


class _SteppingClock:
    """Clock that advances a fixed amount on every read.

    A watched child runs asynchronously, so a test cannot advance a
    frozen clock between its lines. Stepping on each read makes the
    window close deterministically as the run proceeds.
    """

    def __init__(self, step: float) -> None:
        self.t = 1000.0
        self._step = step

    def __call__(self) -> float:
        self.t += self._step
        return self.t


class TestProgressDigest:
    def test_first_line_flushes_so_a_run_shows_life_at_once(self):
        clock = _FakeClock()
        digest = ProgressDigest(kind="deploy", flush_seconds=100.0, time_source=clock)
        assert digest.add("--- Stage: build ---\n") == (
            "# watch_deploy digest: --- Stage: build ---\n"
        )

    def test_lines_inside_the_window_are_held(self):
        clock = _FakeClock()
        digest = ProgressDigest(kind="deploy", flush_seconds=100.0, time_source=clock)
        digest.add("--- Stage: build ---\n")
        clock.advance(10.0)
        assert digest.add("  Workflow run ID: 42\n") is None
        assert digest.add("  Stage 'build' completed successfully\n") is None

    def test_the_window_releases_every_held_line_in_order(self):
        clock = _FakeClock()
        digest = ProgressDigest(kind="deploy", flush_seconds=100.0, time_source=clock)
        digest.add("--- Stage: build ---\n")
        digest.add("  Workflow run ID: 42\n")
        digest.add("  Stage 'build' completed successfully\n")
        clock.advance(100.0)
        released = digest.add("--- Stage: promote ---\n")
        assert released == (
            "# watch_deploy digest: "
            + DIGEST_SEPARATOR.join(
                (
                    "Workflow run ID: 42",
                    "Stage 'build' completed successfully",
                    "--- Stage: promote ---",
                )
            )
            + "\n"
        )

    def test_the_label_names_the_run_a_digest_summarises(self):
        digest = ProgressDigest(
            kind="deploy", label="run-20260902-001", flush_seconds=100.0
        )
        assert digest.add("--- Stage: build ---\n").startswith(
            "# watch_deploy digest run-20260902-001: "
        )

    def test_flush_is_empty_when_nothing_is_held(self):
        digest = ProgressDigest(kind="deploy", flush_seconds=100.0)
        assert digest.flush() is None

    def test_zero_seconds_passes_every_line_straight_through(self):
        digest = ProgressDigest(kind="deploy", flush_seconds=0.0)
        assert digest.batching is False
        for line in ("--- Stage: build ---\n", "  Workflow run ID: 42\n"):
            assert digest.add(line) == line
        assert digest.flush() is None

    def test_seconds_until_flush_is_none_with_an_empty_buffer(self):
        clock = _FakeClock()
        digest = ProgressDigest(kind="deploy", flush_seconds=100.0, time_source=clock)
        assert digest.seconds_until_flush() is None
        digest.add("--- Stage: build ---\n")
        clock.advance(40.0)
        digest.add("  Workflow run ID: 42\n")
        assert digest.seconds_until_flush() == pytest.approx(60.0)


class TestFlushSecondsOption:
    def test_the_flag_is_pulled_out_of_any_position(self):
        argv, seconds = _watch_digest.extract_flush_seconds(
            ["run-1", "--", "--flush-seconds", "30", "--force"]
        )
        assert argv == ["run-1", "--", "--force"]
        assert seconds == 30.0

    def test_the_equals_form_is_equivalent(self):
        argv, seconds = _watch_digest.extract_flush_seconds(
            ["--flush-seconds=0", "run-1"]
        )
        assert argv == ["run-1"]
        assert seconds == 0.0

    def test_an_absent_flag_resolves_to_the_constant(self):
        argv, seconds = _watch_digest.extract_flush_seconds(["run-1"])
        assert argv == ["run-1"]
        assert seconds is None
        assert (
            _watch_digest.resolve_flush_seconds(object(), seconds)
            == DEFAULT_FLUSH_SECONDS
        )

    @pytest.mark.parametrize("bad", ["banana", "-1"])
    def test_an_unusable_value_refuses_with_the_repair(self, bad):
        with pytest.raises(SystemExit) as raised:
            _watch_digest.extract_flush_seconds(["--flush-seconds", bad])
        assert "--flush-seconds" in str(raised.value)

    def test_a_missing_value_refuses_with_the_repair(self):
        with pytest.raises(SystemExit) as raised:
            _watch_digest.extract_flush_seconds(["--flush-seconds"])
        assert "needs a value" in str(raised.value)

    def test_an_explicit_window_travels_with_a_pasted_pair(self):
        assert _watch_digest.streaming_pair_options(30.0) == [
            "--flush-seconds",
            "30",
        ]
        assert _watch_digest.streaming_pair_options(None) == []


def _emit_lines_script(tmp_path: Path, lines: list[str]) -> Path:
    """Write a Python emitter that prints *lines* in order and exits 0."""
    script = tmp_path / "emit.py"
    body = "\n".join(
        ["lines = " + repr(lines), "for line in lines:", "    print(line)"]
    )
    script.write_text(body + "\n", encoding="utf-8")
    return script


def _run(
    *,
    tmp_path: Path,
    lines: list[str],
    flush_seconds: float,
    time_source=None,
) -> str:
    """Run the deploy watcher over *lines*; return the progress capture."""
    script = _emit_lines_script(tmp_path, lines)
    progress = tmp_path / "progress.log"
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=watch_deploy.classify_deploy_line,
        raw_capture=tmp_path / "raw.log",
        progress_capture=progress,
        kind="deploy",
        stdout_stream=io.StringIO(),
        time_source=time_source or _FakeClock(),
        flush_seconds=flush_seconds,
        digest_label="run-20260902-001",
    )
    assert rc == 0
    return progress.read_text(encoding="utf-8")


STAGE_LINES = [
    "--- Stage: build (step_runner: github-actions-workflow) ---",
    "  Workflow run ID: 30970494088",
    "  Stage 'build' completed successfully",
    "--- Stage: promote (step_runner: github-actions-workflow) ---",
    "  Workflow run ID: 30970494099",
    "  Stage 'promote' completed successfully",
]


class TestRunnerDigest:
    def test_completion_releases_a_window_the_run_ended_inside(self, tmp_path):
        progress = _run(
            tmp_path=tmp_path, lines=STAGE_LINES, flush_seconds=DEFAULT_FLUSH_SECONDS
        )
        digests = [
            ln for ln in progress.splitlines() if " digest run-20260902-001: " in ln
        ]
        # One digest opens the run, one closes it at completion; between
        # them a frozen clock never reaches the window.
        assert len(digests) == 2
        assert digests[0].endswith(STAGE_LINES[0])
        for line in STAGE_LINES[1:]:
            assert line.strip() in digests[1]
        assert digests[1].count(DIGEST_SEPARATOR) == len(STAGE_LINES) - 2

    def test_an_urgent_line_carries_the_progress_buffered_before_it(
        self, tmp_path
    ):
        lines = [
            *STAGE_LINES[:3],
            "Error: promote stage failed (exit 1)",
            *STAGE_LINES[3:],
        ]
        progress = _run(
            tmp_path=tmp_path, lines=lines, flush_seconds=DEFAULT_FLUSH_SECONDS
        )
        emitted = [
            ln
            for ln in progress.splitlines()
            if " digest run-20260902-001: " in ln or ln.startswith("Error:")
        ]
        # The error is preceded by the motion that led to it rather than
        # arriving alone, and the run's remaining motion follows it.
        assert emitted[1].startswith("# watch_deploy digest")
        assert "Workflow run ID: 30970494088" in emitted[1]
        assert emitted[2] == "Error: promote stage failed (exit 1)"
        assert emitted[3].startswith("# watch_deploy digest")

    def test_the_window_releases_mid_run_without_waiting_for_the_end(
        self, tmp_path
    ):
        progress = _run(
            tmp_path=tmp_path,
            lines=STAGE_LINES,
            flush_seconds=20.0,
            time_source=_SteppingClock(step=10.0),
        )
        digests = [
            ln for ln in progress.splitlines() if " digest run-20260902-001: " in ln
        ]
        # A clock that advances as the run proceeds closes the window
        # repeatedly, and every line still lands exactly once.
        assert len(digests) > 2
        joined = "\n".join(digests)
        for line in STAGE_LINES:
            assert joined.count(line.strip()) == 1

    def test_zero_restores_one_emission_per_progress_line(self, tmp_path):
        progress = _run(tmp_path=tmp_path, lines=STAGE_LINES, flush_seconds=0.0)
        assert "digest" not in progress
        for line in STAGE_LINES:
            assert line.strip() in progress

    def test_the_raw_capture_keeps_every_line_unchanged(self, tmp_path):
        _run(
            tmp_path=tmp_path, lines=STAGE_LINES, flush_seconds=DEFAULT_FLUSH_SECONDS
        )
        raw = (tmp_path / "raw.log").read_text(encoding="utf-8")
        assert raw.splitlines() == STAGE_LINES
