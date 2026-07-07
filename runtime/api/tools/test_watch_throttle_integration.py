"""Runner-level integration tests for the throttle pipeline.

Exercises :func:`yoke_core.tools._watch_runner.run_watcher` against
synthetic streams with the throttle gate active, plus the watcher
classifier round-trips. Unit-level tests for the standalone primitives
live in ``test_watch_throttle.py``.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from yoke_core.tools import _watch_runner, watch_merge, watch_pytest
from yoke_core.tools._watch_throttle import (
    LineClass,
    ThrottlePolicy,
)


class _FakeClock:
    """Frozen monotonic clock — no time-window emissions in these tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def _emit_lines_script(tmp_path: Path, lines: list[str]) -> Path:
    """Write a Python emitter that prints *lines* in order and exits 0."""
    script = tmp_path / "emit.py"
    body = "\n".join(
        ["import sys", "lines = " + repr(lines), "for line in lines:", "    print(line)"]
    )
    script.write_text(body + "\n", encoding="utf-8")
    return script


def _run_against_lines(
    *,
    tmp_path: Path,
    lines: list[str],
    policy: ThrottlePolicy,
    classifier=None,
) -> tuple[str, str, str]:
    """Run the watcher against a synthetic stream and return all surfaces."""
    script = _emit_lines_script(tmp_path, lines)
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    stdout = io.StringIO()
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=classifier or watch_pytest.classify_pytest_line,
        raw_capture=raw,
        progress_capture=progress,
        kind="pytest",
        stdout_stream=stdout,
        policy=policy,
        time_source=_FakeClock(),
    )
    assert rc == 0
    return (
        raw.read_text(encoding="utf-8"),
        progress.read_text(encoding="utf-8"),
        stdout.getvalue(),
    )


class TestRunnerProgressFlood:
    def test_pure_progress_flood_throttles_with_annotation(self, tmp_path):
        # 30 lines of single-percent ticks 1..30. With a 5-step policy
        # and frozen time, only ticks at 1, 6, 11, 16, 21, 26 emit — at
        # most one progress line per >=5% jump.
        lines = [
            f"runtime/api/test_x.py ...      [{p:>3}%]" for p in range(1, 31)
        ]
        policy = ThrottlePolicy(percent_step=5.0, min_interval_seconds=999.0)
        raw_text, progress_text, stdout_text = _run_against_lines(
            tmp_path=tmp_path, lines=lines, policy=policy
        )

        # Raw capture is byte-equivalent to underlying stream.
        for p in range(1, 31):
            assert f"[{p:>3}%]" in raw_text

        progress_emitted = [
            ln for ln in progress_text.splitlines() if "%]" in ln
        ]
        # 6 emissions: 1, 6, 11, 16, 21, 26.
        assert len(progress_emitted) == 6
        # The second emission and onwards carry the suppression annotation.
        assert "(suppressed 4 ticks)" in progress_emitted[1]
        # Stdout matches progress capture for emitted lines.
        for emitted in progress_emitted:
            assert emitted in stdout_text

    def test_raw_capture_never_carries_annotation(self, tmp_path):
        lines = [
            f"runtime/api/test_x.py ...    [{p:>3}%]" for p in range(1, 11)
        ]
        policy = ThrottlePolicy(percent_step=5.0, min_interval_seconds=999.0)
        raw_text, progress_text, _ = _run_against_lines(
            tmp_path=tmp_path, lines=lines, policy=policy
        )
        assert "(suppressed" in progress_text
        assert "(suppressed" not in raw_text

    def test_total_suppressed_in_footer_when_run_ends_mid_window(
        self, tmp_path
    ):
        # 4 progress lines at 1%, 2%, 3%, 4% with a 50-step policy.
        # Only the first emits; the remaining 3 are suppressed and the
        # run ends before any further emission. The footer carries the
        # residual count so the operator can see the trailing
        # suppression at a glance.
        lines = [
            f"runtime/api/test_x.py ...      [{p:>3}%]" for p in (1, 2, 3, 4)
        ]
        policy = ThrottlePolicy(percent_step=50.0, min_interval_seconds=999.0)
        raw_text, progress_text, _ = _run_against_lines(
            tmp_path=tmp_path, lines=lines, policy=policy
        )
        footer = progress_text.splitlines()[-1]
        assert "suppressed_total=3" in footer
        assert "suppressed_pending=3" in footer
        # Raw capture footer is absent — wrapper banners never enter raw.
        assert "suppressed_total" not in raw_text


class TestRunnerInterleavedUrgent:
    def test_urgent_emits_immediately_amid_throttled_progress(self, tmp_path):
        # Progress flood with a FAILED line in the middle. The FAILED
        # line MUST emit in the same poll cycle — no throttling.
        lines = [
            "runtime/api/test_x.py ...      [  1%]",
            "runtime/api/test_x.py ...      [  2%]",
            "runtime/api/test_x.py ...      [  3%]",
            "FAILED runtime/api/test_x.py::test_thing - assert 1 == 2",
            "runtime/api/test_x.py ...      [  4%]",
            "runtime/api/test_x.py ...      [  5%]",
        ]
        policy = ThrottlePolicy(percent_step=10.0, min_interval_seconds=999.0)
        _, progress_text, stdout_text = _run_against_lines(
            tmp_path=tmp_path, lines=lines, policy=policy
        )

        # Urgent line lands in progress AND stdout regardless of cadence.
        assert "FAILED runtime/api/test_x.py::test_thing" in progress_text
        assert "FAILED runtime/api/test_x.py::test_thing" in stdout_text
        # Urgent lines are never annotated with the suppression suffix.
        for line in progress_text.splitlines():
            if line.startswith("FAILED "):
                assert "(suppressed" not in line


class TestRunnerSlowProgressNoThrottleNeeded:
    def test_every_progress_line_emits_when_steps_far_apart(self, tmp_path):
        # 4 progress lines spaced 30% apart with a 5% step policy and
        # frozen time. Each line crosses the step on its own — no
        # suppression should occur.
        lines = [
            f"runtime/api/test_x.py ...    [{p:>3}%]"
            for p in (10, 40, 70, 100)
        ]
        policy = ThrottlePolicy(percent_step=5.0, min_interval_seconds=999.0)
        _, progress_text, _ = _run_against_lines(
            tmp_path=tmp_path, lines=lines, policy=policy
        )
        progress_emitted = [
            ln for ln in progress_text.splitlines() if "%]" in ln
        ]
        assert len(progress_emitted) == 4
        for ln in progress_emitted:
            assert "(suppressed" not in ln


class TestPytestClassifier:
    @pytest.mark.parametrize(
        "line, expected_cls, expected_value",
        [
            ("runtime/api/test_x.py ...     [ 47%]", LineClass.PROGRESS, 47.0),
            ("runtime/api/test_x.py F       [100%]", LineClass.PROGRESS, 100.0),
            ("FAILED runtime/api/test_x.py::test_y", LineClass.URGENT, None),
            (
                "ERROR runtime/api/test_x.py - ImportError",
                LineClass.URGENT,
                None,
            ),
            (
                "============= 1 failed, 3 passed in 0.4s =============",
                LineClass.SUMMARY,
                None,
            ),
            ("collected 12 items", LineClass.SUMMARY, None),
            ("platform darwin -- Python 3.11", LineClass.NOISE, None),
        ],
    )
    def test_classifies(self, line, expected_cls, expected_value):
        result = watch_pytest.classify_pytest_line(line)
        assert result.cls is expected_cls
        assert result.progress_value == expected_value


class TestMergeClassifier:
    @pytest.mark.parametrize(
        "line, expected_cls",
        [
            ("=== Done transition: YOK-1 ===", LineClass.SUMMARY),
            ("Pre-flight: merge already completed", LineClass.SUMMARY),
            ("Branch already merged — skipping", LineClass.SUMMARY),
            ("Resuming from step 6", LineClass.SUMMARY),
            ("Merging branch: YOK-1 -> main", LineClass.SUMMARY),
            ("Worktree: /repo/.worktrees/YOK-1", LineClass.SUMMARY),
            ("Merge already completed; skipping", LineClass.SUMMARY),
            ("RESULT_FILE=/tmp/result.json", LineClass.SUMMARY),
            ("YOKE_REPO_ROOT=/repo", LineClass.SUMMARY),
            ("Error: merge phase 'rebase' failed", LineClass.URGENT),
            ("ERROR: synthetic", LineClass.URGENT),
            ("Warning: branch mismatch detected", LineClass.URGENT),
            ("HARD STOP: User-authored files at risk", LineClass.URGENT),
            ("Merge halted: agent resolution required", LineClass.URGENT),
            ("Merge lock error: lease held by other session", LineClass.URGENT),
            ("fatal: not a git repository", LineClass.URGENT),
            ("Step 4: rebase onto main", LineClass.PROGRESS),
            ("[tests] runtime/api/test_x.py ... [ 47%]", LineClass.PROGRESS),
            (
                "[tests] FAILED runtime/api/test_x.py::test_y - assert 1 == 2",
                LineClass.URGENT,
            ),
            ("[tests] ERROR runtime/api/test_x.py - ImportError", LineClass.URGENT),
            (
                "[tests] ============== 1 failed, 2 passed ==============",
                LineClass.SUMMARY,
            ),
            (
                "[phase:tests] project command (full): pytest",
                LineClass.PROGRESS,
            ),
            ("[phase:smoke-prep] starting", LineClass.PROGRESS),
            ("ordinary diagnostic detail", LineClass.NOISE),
            ("Title: Some title", LineClass.NOISE),
        ],
    )
    def test_classifies(self, line, expected_cls):
        result = watch_merge.classify_merge_line(line)
        assert result.cls is expected_cls

    def test_prefixed_percent_carries_progress_value(self):
        result = watch_merge.classify_merge_line(
            "[tests] runtime/api/test_x.py ... [ 47%]"
        )
        assert result.cls is LineClass.PROGRESS
        assert result.progress_value == 47.0

    def test_step_progress_throttled_in_runner(self, tmp_path):
        # Many merge test lines arriving fast should throttle by percent
        # step with a frozen clock — ensures merge tests cannot flood the
        # transcript even though they share the watcher path.
        lines = [
            f"[tests] runtime/api/test_x.py ... [ {p}%]"
            for p in range(1, 21)
        ]
        script = _emit_lines_script(tmp_path, lines)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=watch_merge.classify_merge_line,
            raw_capture=raw,
            progress_capture=progress,
            kind="merge",
            stdout_stream=io.StringIO(),
            policy=ThrottlePolicy(
                percent_step=5.0, min_interval_seconds=999.0
            ),
            time_source=_FakeClock(),
        )
        assert rc == 0
        progress_lines = [
            ln
            for ln in progress.read_text(encoding="utf-8").splitlines()
            if "[tests]" in ln
        ]
        # Percent values emit at 1, 6, 11, and 16 with a 5-point step.
        assert len(progress_lines) == 4
        footer = progress.read_text(encoding="utf-8").splitlines()[-1]
        assert "suppressed_total=16" in footer

    def test_prefixed_failure_bypasses_progress_throttle(self, tmp_path):
        lines = [
            "[tests] runtime/api/test_x.py ... [ 1%]",
            "[tests] runtime/api/test_x.py ... [ 2%]",
            "[tests] FAILED runtime/api/test_x.py::test_y - assert 1 == 2",
            "[tests] runtime/api/test_x.py ... [ 3%]",
        ]
        script = _emit_lines_script(tmp_path, lines)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()
        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=watch_merge.classify_merge_line,
            raw_capture=raw,
            progress_capture=progress,
            kind="merge",
            stdout_stream=stdout,
            policy=ThrottlePolicy(
                percent_step=50.0, min_interval_seconds=999.0
            ),
            time_source=_FakeClock(),
        )
        assert rc == 0
        progress_text = progress.read_text(encoding="utf-8")
        stdout_text = stdout.getvalue()
        assert "[tests] FAILED runtime/api/test_x.py::test_y" in progress_text
        assert "[tests] FAILED runtime/api/test_x.py::test_y" in stdout_text
        for line in progress_text.splitlines():
            if line.startswith("[tests] FAILED "):
                assert "(suppressed" not in line
