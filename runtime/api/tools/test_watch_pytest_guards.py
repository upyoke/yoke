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
    def test_collection_and_usage_errors_classify_urgent(self, line: str) -> None:
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
    def test_collection_outcome_lines_classify_summary(self, line: str) -> None:
        assert watch_pytest.classify_pytest_line(line).cls is LineClass.SUMMARY

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


class TestExplicitFileSelectionDiagnostics:
    def test_missing_file_refuses_the_complete_selection(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        present = tmp_path / "test_present.py"
        present.write_text("def test_present():\n    assert True\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            watch_pytest._watch_runner,
            "run_watcher",
            lambda **_kwargs: pytest.fail("invalid selection reached pytest"),
        )

        rc = watch_pytest.main(["--", "test_present.py", "test_missing.py"])

        assert rc == _watch_pytest_args.PYTEST_USAGE_ERROR_EXIT_STATUS
        captured = capsys.readouterr()
        assert "2 supplied test file(s), 1 missing" in captured.err
        assert (
            "test_present.py — exists; not run because the combined "
            "selection is invalid"
        ) in captured.err
        assert "test_missing.py — path does not exist" in captured.err
        assert captured.out == ""

    def test_zero_collection_names_each_file_and_active_filter(self, tmp_path) -> None:
        for name in ("test_one.py", "test_two.py"):
            (tmp_path / name).write_text(
                "def test_present():\n    assert True\n", encoding="utf-8"
            )

        diagnostic = _watch_pytest_args.zero_collection_diagnostic(
            ["test_one.py", "test_two.py", "-k", "absent_name"],
            0,
            tmp_path,
        )

        assert diagnostic is not None
        assert "2 supplied test file(s)" in diagnostic
        assert (
            "test_one.py — no item matched active filter(s): -k absent_name"
            in diagnostic
        )
        assert (
            "test_two.py — no item matched active filter(s): -k absent_name"
            in diagnostic
        )

    def test_nonzero_collection_needs_no_diagnostic(self, tmp_path) -> None:
        (tmp_path / "test_one.py").write_text(
            "def test_present():\n    assert True\n", encoding="utf-8"
        )

        assert (
            _watch_pytest_args.zero_collection_diagnostic(["test_one.py"], 1, tmp_path)
            is None
        )

    def test_main_emits_zero_collection_diagnostic_in_footer(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        observed = {}

        def _zero_item_run(**kwargs):
            kwargs["classifier"]("4 workers [0 items]")
            observed["footer"] = kwargs["footer_metadata"]()
            return 5

        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        monkeypatch.setattr(
            watch_pytest.verification_tree_binding,
            "evaluate_run",
            lambda **_kwargs: (
                watch_pytest.verification_tree_binding.TreeBindingVerdict()
            ),
        )
        monkeypatch.setattr(
            watch_pytest._source_pythonpath,
            "import_origin_refusal",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(watch_pytest._watch_runner, "run_watcher", _zero_item_run)
        monkeypatch.setattr(
            watch_pytest._watch_pytest_wall_clock,
            "report",
            lambda *_args, **_kwargs: None,
        )

        rc = watch_pytest.main(
            ["--", "runtime/api/tools/test_watch_pytest_guards.py", "-k", "absent"]
        )

        assert rc == 5
        assert "zero-collection selection" in observed["footer"]
        assert "no item matched active filter(s): -k absent" in observed["footer"]
