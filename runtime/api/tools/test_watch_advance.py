"""Tests for ``yoke_core.tools.watch_advance``.

Covers the line classifier against representative orchestrator output
fixtures (worktree-phase progress lines, validation surface provisioning,
final JSON summary, error/blocked lines, noise), the nested-invocation
rejection path, position-tolerant ``--`` separator parsing, exit-code
passthrough, and the ``--print-streaming-pair`` shape.
"""

from __future__ import annotations

import io
import os
import shlex
import sys

import pytest

from yoke_core.tools import _watch_runner, watch_advance
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass


class TestAdvanceClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "Playwright cache: /Users/foo/.yoke/playwright-cache/yoke",
            "Installing deps via project setup_command: npm ci",
            "Detected nested package-lock.json at browser — running npm ci",
            "Detected nested requirements.txt at api — running pip install",
            "No dependency files detected — skipping install",
            "Validation surface provisioned: primary -> /tmp/validation.db",
            "Status is still 'reviewed-implementation' — retrying in 2 seconds...",
        ],
    )
    def test_progress_lines_classify(self, line: str) -> None:
        cls = watch_advance.classify_advance_line(line)
        assert cls.cls is LineClass.PROGRESS

    @pytest.mark.parametrize(
        "line",
        [
            "ERROR: invalid item id 'YOK-foo'",
            "ERROR: YOK-99999 not found.",
            "ERROR: orchestrator crashed: KeyError",
            "ERROR: finalize failed (gate_blocked): hard-block dep",
            "BLOCKED: YOK-1755 File Budget lists 3 path(s) not covered.",
            "Warning: validation-surface provisioning failed (non-fatal): perms",
            "Warning: validation surface for model 'gov' at /tmp failed: ENOENT",
            "Status update failed after 3 attempts.",
            "HARD STOP: User-authored files at risk.",
        ],
    )
    def test_urgent_lines_classify(self, line: str) -> None:
        cls = watch_advance.classify_advance_line(line)
        assert cls.cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            '{"item_id": 1755, "title": "x", "pre_status": "refined-idea"}',
            '{"item_id": 42, "phases": []}',
        ],
    )
    def test_summary_lines_classify(self, line: str) -> None:
        cls = watch_advance.classify_advance_line(line)
        assert cls.cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving DB path...",
            "irrelevant noise",
            "added 47 packages from 22 contributors",
            "",
        ],
    )
    def test_noise_lines_classify(self, line: str) -> None:
        cls = watch_advance.classify_advance_line(line)
        assert cls.cls is LineClass.NOISE


class TestUnionPattern:
    def test_progress_lines_match_union(self) -> None:
        for line in (
            "Playwright cache: /tmp",
            "Detected nested package-lock.json at b — running npm ci",
            "Validation surface provisioned: primary -> /tmp/v.db",
        ):
            assert filter_match(watch_advance.ADVANCE_PROGRESS_PATTERN, line)

    def test_urgent_lines_match_union(self) -> None:
        for line in (
            "ERROR: invalid item id 'foo'",
            "BLOCKED: missing path",
            "Warning: thing broke",
        ):
            assert filter_match(watch_advance.ADVANCE_PROGRESS_PATTERN, line)

    def test_summary_lines_match_union(self) -> None:
        for line in (
            '{"item_id": 1, "phases": []}',
            '{"item_id": 999, "title": "x"}',
        ):
            assert filter_match(watch_advance.ADVANCE_PROGRESS_PATTERN, line)


class TestNestedAdvanceRejection:
    @pytest.mark.parametrize(
        "args",
        [
            ["python3", "-m", "yoke_core.engines.advance_implementation_entry"],
            ["python3", "-m", "yoke_core.engines.advance_implementation_entry", "--item", "YOK-1"],
            ["python", "-m", "yoke_core.engines.advance_implementation_entry"],
            ["/usr/bin/python3", "-m", "yoke_core.engines.advance_implementation_entry"],
            ["sys.executable", "-m", "yoke_core.engines.advance_implementation_entry"],
        ],
    )
    def test_nested_invocation_detected(self, args: list[str]) -> None:
        assert watch_advance._is_nested_advance_invocation(args)

    @pytest.mark.parametrize(
        "args",
        [
            ["--item", "YOK-1"],
            ["--item", "YOK-1", "--force"],
            [],
            ["python3", "-m", "pytest"],
            ["python3", "-m", "yoke_core.engines.done_transition"],
        ],
    )
    def test_non_nested_invocations_pass(self, args: list[str]) -> None:
        assert not watch_advance._is_nested_advance_invocation(args)


class TestAdvanceArgv:
    def test_argv_includes_module_prefix(self) -> None:
        argv = watch_advance._advance_argv(["--item", "YOK-1755"])
        assert argv[0] == sys.executable
        assert argv[1:] == [
            "-m",
            "yoke_core.engines.advance_implementation_entry",
            "--item",
            "YOK-1755",
        ]


class TestPrintStreamingPair:
    def test_print_streaming_pair_emits_three_line_block(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_advance.main(["--print-streaming-pair", "--", "--item", "YOK-1"])
        assert rc == 0
        out = capsys.readouterr().out
        # Background command line uses the wrapper module + explicit
        # captures + the underlying args after ``--``.
        anchor = f"cd {shlex.quote(os.getcwd())} && uv run --frozen python3 -m"
        assert f"{anchor} yoke_core.tools.watch_advance" in out
        assert "PYTHONPATH" not in out
        assert "--raw-capture" in out
        assert "--progress-capture" in out
        assert "--item YOK-1" in out
        # Progress-tail line uses watch_tail against the progress capture.
        assert f"{anchor} yoke_core.tools.watch_tail" in out
        # Post-completion inspection.
        assert "tail -80" in out

    def test_print_streaming_pair_flag_position_tolerant(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Flag placed AFTER the ``--`` separator still pre-extracted.
        rc = watch_advance.main(["--", "--item", "YOK-1", "--print-streaming-pair"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "yoke_core.tools.watch_advance" in out
        assert "--item YOK-1" in out


class TestPassthroughSeparator:
    def test_leading_separator_is_stripped(self) -> None:
        ns = watch_advance._parse_args(["--", "--item", "YOK-1755"])
        stripped = watch_advance._strip_separator(list(ns.passthrough))
        assert stripped == ["--item", "YOK-1755"]

    def test_strip_separator_is_a_noop_on_clean_args(self) -> None:
        # The first arg is treated as the start of REMAINDER even when
        # it does not start with ``--``. Wrapper callers who pass bare
        # positionals (no flag-like leading args) do not need ``--`` and
        # the strip is a no-op.
        stripped = watch_advance._strip_separator(["YOK-1755"])
        assert stripped == ["YOK-1755"]


class TestExitCodePassthrough:
    """Verify the wrapper preserves the underlying command's exit code.

    Uses the real ``_watch_runner.run_watcher`` with a fake argv that
    invokes a Python one-liner returning a chosen exit code, so we
    exercise the full stdout/stderr capture path without depending on
    the orchestrator's real DB / worktree side effects.
    """

    def test_zero_exit_is_passed_through(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        argv = [
            sys.executable,
            "-c",
            "import sys; print('Playwright cache: /tmp/cache'); sys.exit(0)",
        ]
        stream = io.StringIO()
        rc = _watch_runner.run_watcher(
            argv=argv,
            classifier=watch_advance.classify_advance_line,
            raw_capture=raw,
            progress_capture=progress,
            kind=watch_advance.KIND,
            stdout_stream=stream,
        )
        assert rc == 0

    def test_nonzero_exit_is_passed_through(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        argv = [
            sys.executable,
            "-c",
            "import sys; print('ERROR: nope', file=sys.stderr); sys.exit(7)",
        ]
        stream = io.StringIO()
        rc = _watch_runner.run_watcher(
            argv=argv,
            classifier=watch_advance.classify_advance_line,
            raw_capture=raw,
            progress_capture=progress,
            kind=watch_advance.KIND,
            stdout_stream=stream,
        )
        assert rc == 7


class TestSentinelAutoExit:
    """The wrapper writes ``# watch_advance exit=<rc>`` as the final
    line of the progress capture. ``watch_tail`` reads this sentinel
    and auto-exits, so a Monitor armed against the progress capture
    terminates cleanly when the underlying command finishes.
    """

    def test_exit_sentinel_emitted(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        argv = [
            sys.executable,
            "-c",
            "print('Playwright cache: /tmp/cache')",
        ]
        rc = _watch_runner.run_watcher(
            argv=argv,
            classifier=watch_advance.classify_advance_line,
            raw_capture=raw,
            progress_capture=progress,
            kind=watch_advance.KIND,
            stdout_stream=io.StringIO(),
        )
        assert rc == 0
        # The sentinel is the LAST line of the progress capture.
        progress_text = progress.read_text(encoding="utf-8")
        progress_lines = [
            line for line in progress_text.splitlines() if line.strip()
        ]
        assert progress_lines[-1].startswith("# watch_advance exit=0")
