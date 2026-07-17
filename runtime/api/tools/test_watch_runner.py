"""Tests for the shared watcher runner.

Covers:
- Raw vs progress capture split (matching lines vs non-matching diagnostics).
- Stdout streaming of filtered progress.
- Exit-code preservation including a synthetic non-zero command.
- Wrapper-launch error path when the underlying binary cannot be found.
- Metadata header / footer emitted to both progress capture and stdout.
- ``mint_capture_paths`` produces fresh files under the project scratch
  root via :mod:`yoke_core.domain.project_scratch_dir`, sharing a
  single nonce between the raw and progress paths.
- ``regex_classifier`` adapter promotes a single regex into a classifier
  whose progress lines pass through the throttle gate.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ThrottlePolicy,
)


# A simple line-oriented filter that matches lines starting with "MATCH".
SIMPLE_FILTER = re.compile(r"^MATCH")
# A throttle policy with effectively-no throttling so test fixtures that
# don't care about cadence emit every progress line they see.
PASSTHROUGH_POLICY = ThrottlePolicy(
    percent_step=0.0001, min_interval_seconds=0.0001
)


def _python_emit_script(tmp_path: Path, lines: list[str], exit_code: int) -> Path:
    """Write a Python script that prints *lines* and exits with *exit_code*."""
    script = tmp_path / "emit.py"
    body_lines = [
        "import sys",
        "lines = " + repr(lines),
        "for line in lines:",
        "    print(line)",
        f"sys.exit({exit_code})",
    ]
    script.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return script


def _summary_classifier(line: str) -> Classification:
    """Treat MATCH-prefixed lines as SUMMARY (immediate, never throttled)."""
    if SIMPLE_FILTER.search(line):
        return Classification(LineClass.SUMMARY)
    return Classification(LineClass.NOISE)


class TestMintCapturePaths:
    def test_returns_fresh_helper_resolved_pair(self, tmp_path, monkeypatch):
        # Pin scratch root under tmp_path. Two pairs must differ; raw +
        # progress within a pair must share one nonce (the correlation
        # ``watch_tail`` relies on); paths land under the helper's
        # ``watcher-captures`` subdir — never bare ``tempfile.mkstemp``.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        raw1, prog1 = _watch_runner.mint_capture_paths("kindx")
        raw2, prog2 = _watch_runner.mint_capture_paths("kindx")
        try:
            assert raw1 != raw2 and prog1 != prog2
            assert all(p.exists() for p in (raw1, raw2, prog1, prog2))
            for raw, prog in ((raw1, prog1), (raw2, prog2)):
                nonce_r = raw.name.removeprefix(
                    "yoke-kindx.raw.").removesuffix(".log")
                nonce_p = prog.name.removeprefix(
                    "yoke-kindx.progress.").removesuffix(".log")
                assert nonce_r == nonce_p
                assert raw.parent == prog.parent
                assert raw.parent.name == "watcher-captures"
                assert tmp_path in raw.parents
        finally:
            for p in (raw1, raw2, prog1, prog2):
                p.unlink(missing_ok=True)


class TestFilterMatch:
    def test_matches_when_pattern_present(self):
        assert _watch_runner.filter_match(SIMPLE_FILTER, "MATCH this line\n")

    def test_does_not_match_otherwise(self):
        assert not _watch_runner.filter_match(SIMPLE_FILTER, "noise line\n")


class TestRegexClassifierAdapter:
    def test_matching_line_is_progress(self):
        classifier = _watch_runner.regex_classifier(SIMPLE_FILTER)
        result = classifier("MATCH something\n")
        assert result.cls is LineClass.PROGRESS
        assert result.progress_value is None

    def test_non_matching_line_is_noise(self):
        classifier = _watch_runner.regex_classifier(SIMPLE_FILTER)
        result = classifier("noise here\n")
        assert result.cls is LineClass.NOISE


class TestRunWatcherSplitCapture:
    def test_raw_has_all_lines_progress_only_matches(self, tmp_path):
        script = _python_emit_script(
            tmp_path,
            [
                "MATCH first",
                "diagnostic noise A",
                "MATCH second",
                "diagnostic noise B",
            ],
            exit_code=0,
        )
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="kindx",
            stdout_stream=stdout,
            policy=PASSTHROUGH_POLICY,
        )

        assert rc == 0

        raw_text = raw.read_text(encoding="utf-8")
        assert "MATCH first" in raw_text
        assert "MATCH second" in raw_text
        # Non-matching diagnostic lines MUST still appear in raw — that
        # is the forensic-fidelity guarantee.
        assert "diagnostic noise A" in raw_text
        assert "diagnostic noise B" in raw_text

        progress_text = progress.read_text(encoding="utf-8")
        assert "MATCH first" in progress_text
        assert "MATCH second" in progress_text
        # Non-matching diagnostic lines MUST NOT appear in progress.
        assert "diagnostic noise A" not in progress_text
        assert "diagnostic noise B" not in progress_text

        stdout_text = stdout.getvalue()
        # Filtered progress is also streamed to stdout (Codex parity).
        assert "MATCH first" in stdout_text
        assert "MATCH second" in stdout_text
        assert "diagnostic noise A" not in stdout_text


class TestRunWatcherMetadata:
    def test_header_and_footer_in_progress_and_stdout(self, tmp_path):
        script = _python_emit_script(tmp_path, ["unrelated"], exit_code=0)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="meta",
            stdout_stream=stdout,
            policy=PASSTHROUGH_POLICY,
        )

        assert rc == 0
        progress_text = progress.read_text(encoding="utf-8")
        assert progress_text.startswith("# watch_meta raw=")
        assert "progress=" in progress_text.splitlines()[0]
        assert "argv=" in progress_text.splitlines()[0]
        assert f"raw={raw}" in progress_text.splitlines()[-1]
        assert "exit=0" in progress_text

        stdout_text = stdout.getvalue()
        assert "# watch_meta raw=" in stdout_text
        assert "exit=0" in stdout_text

    def test_metadata_header_and_footer_absent_from_raw(self, tmp_path):
        """Wrapper banners must never enter the raw capture (forensic fidelity)."""
        script = _python_emit_script(tmp_path, ["unrelated"], exit_code=0)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="meta",
            stdout_stream=io.StringIO(),
            policy=PASSTHROUGH_POLICY,
        )
        assert rc == 0
        raw_text = raw.read_text(encoding="utf-8")
        assert "# watch_meta" not in raw_text
        assert "exit=" not in raw_text

    def test_last_summary_emitted_as_terminal_footer_before_exit_sentinel(
        self, tmp_path
    ):
        """The last SUMMARY-classified line is re-emitted as a labeled footer.

        Agents reading the tail of the progress capture after the bg task
        completes need a deterministic verdict location. The runner
        emits ``# watch_<kind> summary: <last summary line>`` immediately
        before the exit sentinel, giving callers a fixed-position
        machine-parseable verdict.
        """
        script = _python_emit_script(
            tmp_path,
            [
                "noise before",
                "MATCH first summary",
                "more noise",
                "MATCH ===== 47 passed in 12.34s =====",
                "trailing noise",
            ],
            exit_code=0,
        )
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="meta",
            stdout_stream=io.StringIO(),
            policy=PASSTHROUGH_POLICY,
        )
        assert rc == 0
        lines = progress.read_text(encoding="utf-8").splitlines()
        # Exit sentinel must be the last line; summary footer must be
        # immediately above it; summary footer must carry the LAST
        # summary-classified line (not the first).
        assert lines[-1].startswith("# watch_meta exit=0")
        assert lines[-2] == (
            "# watch_meta summary: MATCH ===== 47 passed in 12.34s ====="
        )
        # Raw capture never carries wrapper-emitted footer lines.
        raw_text = raw.read_text(encoding="utf-8")
        assert "# watch_meta summary:" not in raw_text

    def test_no_summary_footer_when_no_summary_classified(self, tmp_path):
        """No summary footer when the underlying command emits no SUMMARY lines."""
        script = _python_emit_script(
            tmp_path, ["noise only", "more noise"], exit_code=0,
        )
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="meta",
            stdout_stream=io.StringIO(),
            policy=PASSTHROUGH_POLICY,
        )
        assert rc == 0
        progress_text = progress.read_text(encoding="utf-8")
        assert "# watch_meta summary:" not in progress_text
        # Exit sentinel still lands as before.
        assert progress_text.splitlines()[-1].startswith("# watch_meta exit=0")

    def test_quiet_child_emits_heartbeat_outside_raw(self, tmp_path, monkeypatch):
        script = tmp_path / "quiet.py"
        script.write_text(
            "import time\n"
            "time.sleep(0.25)\n"
            "print('MATCH awake')\n",
            encoding="utf-8",
        )
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()
        monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "0.05")

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="quiet",
            stdout_stream=stdout,
            policy=PASSTHROUGH_POLICY,
        )

        assert rc == 0
        assert "# watch_quiet still running" in progress.read_text(encoding="utf-8")
        assert "# watch_quiet still running" in stdout.getvalue()
        assert "# watch_quiet still running" not in raw.read_text(encoding="utf-8")


class TestRunWatcherExitCodePreservation:
    @pytest.mark.parametrize("code", [0, 1, 2, 5, 42])
    def test_propagates_underlying_exit_code(self, tmp_path, code):
        script = _python_emit_script(tmp_path, ["MATCH only"], exit_code=code)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="exitcheck",
            stdout_stream=io.StringIO(),
            policy=PASSTHROUGH_POLICY,
        )
        assert rc == code


class TestRunWatcherLaunchError:
    def test_returns_wrapper_launch_error_on_missing_binary(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()

        rc = _watch_runner.run_watcher(
            argv=[str(tmp_path / "definitely-not-a-real-binary")],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="bad",
            stdout_stream=stdout,
            policy=PASSTHROUGH_POLICY,
        )
        assert rc == _watch_runner.WRAPPER_LAUNCH_ERROR
        # Launch errors must reach all three surfaces — they are fatal
        # and the operator needs them visible everywhere.
        assert "launch_error" in raw.read_text(encoding="utf-8")
        progress_text = progress.read_text(encoding="utf-8")
        assert "launch_error" in progress_text
        assert "launch_error" in stdout.getvalue()
        # The exit sentinel still lands so armed followers (watch_tail)
        # terminate instead of following forever.
        expected_sentinel = (
            f"# watch_bad exit={_watch_runner.WRAPPER_LAUNCH_ERROR} raw={raw}"
        )
        assert progress_text.splitlines()[-1] == expected_sentinel
        assert expected_sentinel in stdout.getvalue()
        # Wrapper footers never enter the raw capture.
        assert "exit=" not in raw.read_text(encoding="utf-8")


# Streaming-pair emission contract lives in the 350-cap sibling
# ``test_watch_runner_streaming_pair.py``.
