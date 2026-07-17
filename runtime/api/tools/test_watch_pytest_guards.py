"""Tests for watch_pytest's bare-``runtime/`` refusal and the
collection/usage-error relay.

Lives in its own module to keep ``test_watch_pytest.py`` under the
350-line authored-file cap. Covers two field-note classes:

- Bare ``runtime/`` as a pytest path anchors collection at ``runtime/``
  and demotes ``runtime/api/conftest.py`` from initial-conftest status
  (``pytest_plugins`` in a non-top-level conftest fails collection).
  The wrapper refuses the shape with a repair message naming the
  three-anchor full-suite shape ``runtime/api/ runtime/harness/ tests/``.
- Collection/usage error lines (``ERROR: file or directory not
  found:``, ``ERROR: usage:``, argparse detail lines, xdist
  ``INTERNALERROR>``/worker-count lines, ``no tests ran`` verdicts)
  must be relayed by the watcher so diagnosing a bad invocation does
  not require opening the raw capture. URGENT/SUMMARY classes bypass
  the progress throttle structurally (see ``_watch_runner.run_watcher``).
"""

from __future__ import annotations

import pytest

from yoke_core.tools import _watch_pytest_args, watch_pytest
from yoke_core.tools._watch_throttle import LineClass


class TestCollectionErrorRelay:
    @pytest.mark.parametrize(
        "line",
        [
            # Bad path, no xdist — observed verbatim from pytest 8.4.
            "ERROR: file or directory not found: /tmp/definitely_bogus",
            # Bad flag — UsageError lead line.
            "ERROR: usage: python3.14 -m pytest [options] [file_or_dir] [...]",
            # Bad flag — argparse detail line (prog token contains spaces).
            "python3.14 -m pytest: error: unrecognized arguments: --bogus",
            # xdist worker crash frames.
            "INTERNALERROR> Traceback (most recent call last):",
            # Non-top-level conftest error: UsageError lead line shape...
            "ERROR: Defining 'pytest_plugins' in a non-top-level conftest "
            "is no longer supported:",
            # ...and the unprefixed shape inside xdist ERRORS-section blocks.
            "E   Failed: Defining 'pytest_plugins' in a non-top-level "
            "conftest is no longer supported:",
        ],
    )
    def test_collection_and_usage_errors_classify_urgent(
        self, line: str
    ) -> None:
        assert watch_pytest.classify_pytest_line(line).cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            # ERRORS section banner.
            "==================================== ERRORS "
            "====================================",
            # No-tests-ran verdicts: banner and quiet-mode shapes.
            "============================ no tests ran in 0.26s "
            "=============================",
            "no tests ran in 0.01s",
            # xdist collection notice — the only collection signal xdist
            # prints (``2 workers [0 items]`` is the bad-path tell).
            "2 workers [0 items]",
            "10 workers [503 items]",
            "1 workers [1 item]",
        ],
    )
    def test_collection_outcome_lines_classify_summary(
        self, line: str
    ) -> None:
        assert (
            watch_pytest.classify_pytest_line(line).cls is LineClass.SUMMARY
        )

    @pytest.mark.parametrize(
        "noise",
        [
            "created: 2/2 workers",
            "rootdir: /private/tmp",
            "plugins: cov-6.0.0, xdist-3.8.0, timeout-2.4.0",
            "  inifile: None",
            # Indented frames never match the argparse-detail shape.
            "    raise UsageError: error: synthetic",
        ],
    )
    def test_preamble_noise_stays_noise(self, noise: str) -> None:
        assert watch_pytest.classify_pytest_line(noise).cls is LineClass.NOISE


class TestBareRuntimeRefusal:
    @pytest.mark.parametrize(
        "args",
        [
            ["runtime/"],
            ["runtime"],
            ["./runtime/"],
            ["./runtime"],
            ["-n", "auto", "runtime/"],
            ["-q", "runtime/"],
            ["--no-parallel", "runtime"],
            ["runtime/api/", "runtime/"],
        ],
    )
    def test_helper_detects_bare_runtime(self, args: list[str]) -> None:
        assert _watch_pytest_args.has_bare_runtime_path(args) is True

    @pytest.mark.parametrize(
        "args",
        [
            ["runtime/api/", "runtime/harness/"],
            ["runtime/api/tools/test_watch_pytest.py", "-q"],
            # Flag values are not positional paths.
            ["-k", "runtime"],
            ["-m", "runtime"],
            ["--rootdir", "runtime"],
            ["-n", "auto", "runtime/api/"],
            [],
        ],
    )
    def test_helper_accepts_anchored_shapes(self, args: list[str]) -> None:
        assert _watch_pytest_args.has_bare_runtime_path(args) is False

    def test_main_refuses_bare_runtime_with_repair_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_pytest.main(["--", "-n", "auto", "runtime/"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "refuses bare 'runtime/'" in captured.err
        # The repair message names the three-anchor full-suite shape.
        assert "runtime/api/ runtime/harness/ tests/" in captured.err
        assert "non-top-level conftest" in captured.err
        # Nothing lands on stdout: no streaming pair, no progress.
        assert captured.out == ""

    def test_print_streaming_pair_refuses_bare_runtime(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Printing a pair that embeds a doomed command is the same trap.
        rc = watch_pytest.main(["--print-streaming-pair", "--", "runtime/"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "refuses bare 'runtime/'" in captured.err
        assert "watch_tail" not in captured.out

    def test_help_teaches_three_anchor_full_suite_shape(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pin the format width so argparse's epilog wrapping never splits
        # the asserted phrases across lines.
        monkeypatch.setenv("COLUMNS", "200")
        with pytest.raises(SystemExit) as exc_info:
            watch_pytest.main(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "runtime/api/ runtime/harness/ tests/" in out
        assert "bare 'runtime/'" in out
