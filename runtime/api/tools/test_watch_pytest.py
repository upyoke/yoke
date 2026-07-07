"""Tests for ``yoke_core.tools.watch_pytest``.

Covers:
- Filter regex against representative non-TTY pytest output fixtures
  (progress, failures, errors, summary, collection).
- ``--print-streaming-pair`` emits an invocation pair with the right shape.
- A live subprocess smoke that runs the wrapper against a tiny passing
  pytest suite and confirms exit-code preservation plus split capture.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH
from yoke_core.tools import _watch_pytest_args, watch_pytest
from yoke_core.tools._watch_runner import filter_match


# Representative non-TTY pytest output captured by hand. Includes:
# - File-progress lines with [ N%] markers (AC-4 fixture)
# - A FAILED test summary line
# - A collection-error ERROR line
# - A summary banner with mixed pass/fail
# - A bare collection line
# - Diagnostic noise that the filter MUST ignore
PYTEST_FIXTURE_LINES: list[str] = [
    "============================= test session starts ==============================",
    "platform darwin -- Python 3.11.0, pytest-7.4.0, pluggy-1.0.0",
    "rootdir: /tmp/sample",
    "collected 4 items",
    "",
    "tests/test_a.py ...                                                   [ 75%]",
    "tests/test_b.py F                                                     [100%]",
    "",
    "=================================== FAILURES ===================================",
    "______________________________ test_b.test_thing _______________________________",
    "",
    "    def test_thing():",
    ">       assert 1 == 2",
    "E       assert 1 == 2",
    "",
    "tests/test_b.py:3: AssertionError",
    "=========================== short test summary info ============================",
    "FAILED tests/test_b.py::test_thing - assert 1 == 2",
    "ERROR tests/test_c.py - ImportError: No module named 'missing'",
    "========================= 1 failed, 3 passed in 0.42s ==========================",
]


class TestPytestFilterCoverage:
    @pytest.mark.parametrize(
        "line",
        [
            "tests/test_a.py ...                                                   [ 75%]",
            "tests/test_b.py F                                                     [100%]",
            "tests/sub/foo.py ........                                            [  5%]",
        ],
    )
    def test_progress_lines_match(self, line: str) -> None:
        assert filter_match(watch_pytest.PYTEST_PROGRESS_PATTERN, line)

    def test_failed_summary_matches(self) -> None:
        assert filter_match(
            watch_pytest.PYTEST_PROGRESS_PATTERN,
            "FAILED tests/test_b.py::test_thing - assert 1 == 2",
        )

    def test_error_summary_matches(self) -> None:
        assert filter_match(
            watch_pytest.PYTEST_PROGRESS_PATTERN,
            "ERROR tests/test_c.py - ImportError: No module named 'missing'",
        )

    def test_summary_banner_matches(self) -> None:
        assert filter_match(
            watch_pytest.PYTEST_PROGRESS_PATTERN,
            "========================= 1 failed, 3 passed in 0.42s ==========================",
        )

    @pytest.mark.parametrize(
        "quiet_summary",
        [
            "4 passed in 0.42s",
            "1 failed, 2 passed in 0.12s",
            "1 error, 3 passed in 0.42s",
            "2 failed, 1 error, 3 passed in 0.42s",
            "1 error in 0.42s",
            "5 skipped in 0.42s",
            "1 xfailed, 3 passed in 0.42s",
            "2 deselected, 1 passed in 0.42s",
        ],
    )
    def test_quiet_mode_summary_matches(self, quiet_summary: str) -> None:
        """Pytest ``-q`` mode emits summary lines WITHOUT the ``====`` banner.

        The classifier must catch both the banner shape and the bare
        ``<count> <verdict> in <time>`` shape so agents reading
        watch_pytest's progress capture under ``-q`` get the verdict
        line emitted to the progress stream (and re-emitted as the
        terminal summary footer by the shared runner).
        """
        assert filter_match(watch_pytest.PYTEST_PROGRESS_PATTERN, quiet_summary)

    @pytest.mark.parametrize(
        "noise",
        [
            "1 module loaded",  # digit-prefixed but not a verdict word
            "42 tests collected",  # digit-prefixed but uses 'tests' not verdict
            "passed in 0.42s",  # no leading count
            "in 0.42s",  # no count and no verdict word
        ],
    )
    def test_quiet_mode_noise_does_not_match(self, noise: str) -> None:
        """Negative — the quiet-mode pattern requires count + verdict + (, | in )."""
        assert not filter_match(watch_pytest.PYTEST_PROGRESS_PATTERN, noise)

    def test_collected_line_matches(self) -> None:
        assert filter_match(
            watch_pytest.PYTEST_PROGRESS_PATTERN,
            "collected 4 items",
        )

    @pytest.mark.parametrize(
        "noise",
        [
            "============================= test session starts ==============================",
            "platform darwin -- Python 3.11.0, pytest-7.4.0, pluggy-1.0.0",
            "rootdir: /tmp/sample",
            "    def test_thing():",
            ">       assert 1 == 2",
            "E       assert 1 == 2",
            "tests/test_b.py:3: AssertionError",
        ],
    )
    def test_noise_does_not_match(self, noise: str) -> None:
        assert not filter_match(watch_pytest.PYTEST_PROGRESS_PATTERN, noise)

    def test_fixture_distinguishes_signal_from_noise(self) -> None:
        # The fixture is the AC-4 representative output. Verify the filter
        # picks up at least one progress line, the FAILED line, the ERROR
        # line, the collection notice, and the summary banner — but never
        # picks up the "test session starts" or assertion-detail lines.
        signal = [
            line
            for line in PYTEST_FIXTURE_LINES
            if filter_match(watch_pytest.PYTEST_PROGRESS_PATTERN, line)
        ]
        joined = "\n".join(signal)
        assert "[ 75%]" in joined
        assert "[100%]" in joined
        assert "FAILED" in joined
        assert "ERROR" in joined
        assert "collected 4 items" in joined
        assert "1 failed" in joined
        assert "test session starts" not in joined
        # Pure assertion-detail lines (the indented ">" or "E" frames)
        # are covered by the parametrized noise test; the FAILED summary
        # line legitimately includes the assertion text.


class TestPrintStreamingPair:
    def test_print_streaming_pair_emits_pytest_module_invocation(
        self, capsys, monkeypatch, tmp_path
    ):
        # Pin scratch root + free-RAM high so the streaming pair lands
        # helper-resolved captures under tmp_path AND apply_parallel_default
        # emits ``-n auto`` regardless of host load.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        monkeypatch.setattr(
            watch_pytest._source_pythonpath,
            "import_origin_refusal",
            lambda *args, **kwargs: None,
        )
        from yoke_core.tools import _pytest_parallel
        monkeypatch.setattr(
            _pytest_parallel, "_read_free_ram_mb", lambda: 1_000_000
        )
        rc = watch_pytest.main(
            ["--print-streaming-pair", "--", "runtime/api/", "-k", "smoke"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "python3 -m yoke_core.tools.watch_pytest" in out
        assert "PYTHONPATH=" in out
        assert "packages/yoke-core/src" in out
        assert "runtime/api/" in out and "-k smoke" in out
        assert ("-n auto" in out) or (" -n " in out), out
        # Progress tail = auto-exiting watch_tail follower (not `tail -f`);
        # raw inspection = `tail -80`. Helper-resolved captures land under
        # the scratch root's ``watcher-captures`` subdir.
        assert "python3 -m yoke_core.tools.watch_tail" in out
        assert ".progress." in out and ".raw." in out
        assert "tail -80" in out
        assert "watcher-captures" in out
        assert str(tmp_path) in out


def test_local_postgres_auto_worker_env_reaches_runner(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
    monkeypatch.setattr(watch_pytest._watch_worktree_binding, "check", lambda: None)
    monkeypatch.setattr(
        watch_pytest._source_pythonpath,
        "import_origin_refusal",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        watch_pytest._watch_runner,
        "run_watcher",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    assert watch_pytest.main(["--", "-n", "auto", "runtime/api/tools"]) == 0
    assert captured["env"]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "10"
    assert "packages/yoke-core/src" in captured["env"]["PYTHONPATH"]
    assert "-n" in captured["argv"]
    assert "auto" in captured["argv"]


class TestNestedPytestRejection:
    """Guard against `-- python3 -m pytest …` pass-through.

    `_pytest_argv` always prepends `sys.executable -m pytest`, so the
    mistaken shape silently produced `python3 -m pytest python3 -m
    pytest …`. The wrapper now rejects common interpreter prefixes.
    """

    @pytest.mark.parametrize(
        "leading",
        [
            ("python3", "-m", "pytest"),
            ("python", "-m", "pytest"),
            ("python3.11", "-m", "pytest"),
            ("/usr/bin/python3", "-m", "pytest"),
            ("sys.executable", "-m", "pytest"),
        ],
    )
    def test_helper_detects_nested_invocation(
        self, leading: tuple[str, ...]
    ) -> None:
        args = [*leading, "runtime/api/tools/test_watch_pytest.py", "-q"]
        assert _watch_pytest_args.is_nested_pytest_invocation(args) is True

    @pytest.mark.parametrize(
        "args",
        [
            ["runtime/api/", "-q"],
            ["-k", "smoke"],
            ["python3"],  # too short — only one arg
            ["python3", "-m"],  # too short — missing pytest token
            ["python3", "-c", "print('hi')"],  # not pytest
            ["mypython", "-m", "pytest"],  # not a python basename
            [],
        ],
    )
    def test_helper_accepts_other_shapes(self, args: list[str]) -> None:
        assert _watch_pytest_args.is_nested_pytest_invocation(args) is False

    def test_main_rejects_nested_invocation(self, capsys) -> None:
        rc = watch_pytest.main(
            ["--", "python3", "-m", "pytest",
             "runtime/api/tools/test_watch_pytest.py", "-q"]
        )
        assert rc != 0
        captured = capsys.readouterr()
        assert "bare pytest args" in captured.err
        assert "python3 -m pytest" in captured.err
        # Nothing should land on stdout: no streaming-pair output, no
        # filtered progress, no exit sentinel.
        assert captured.out == ""

    def test_print_streaming_pair_rejects_nested_invocation(
        self, capsys, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = watch_pytest.main(
            ["--print-streaming-pair", "--", "python", "-m", "pytest",
             "runtime/api/tools/test_watch_pytest.py", "-q"]
        )
        assert rc != 0
        captured = capsys.readouterr()
        assert "bare pytest args" in captured.err
        # The streaming-pair header and the would-be background command
        # must not be emitted on stdout — that is exactly the silent
        # nested-invocation pass-through this guard prevents.
        assert "-- python" not in captured.out
        assert "watch_pytest" not in captured.out


class TestLiveWrapperSmoke:
    def test_runs_against_passing_test_and_splits_capture(
        self, tmp_path: Path
    ) -> None:
        # Build a tiny self-contained repo with one passing pytest test.
        mini = tmp_path / "mini"
        pkg = mini / "pkgx"
        pkg.mkdir(parents=True)
        (mini / "pyproject.toml").write_text(
            "[project]\nname = 'pkgx'\nversion = '0.0.0'\n"
            "[tool.pytest.ini_options]\ntestpaths = ['pkgx']\n",
            encoding="utf-8",
        )
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "test_one.py").write_text(
            "def test_pass():\n    assert True\n", encoding="utf-8"
        )

        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{SOURCE_PYTHONPATH}{os.pathsep}{mini}"
            f"{os.pathsep}{env.get('PYTHONPATH', '')}"
        )
        # Disable color/TTY so progress markers are emitted in non-TTY form.
        env["NO_COLOR"] = "1"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yoke_core.tools.watch_pytest",
                "--raw-capture",
                str(raw),
                "--progress-capture",
                str(progress),
                "--",
                "pkgx",
            ],
            cwd=str(mini),
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"watch_pytest smoke failed (exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert raw.exists() and progress.exists()
        raw_text = raw.read_text(encoding="utf-8")
        progress_text = progress.read_text(encoding="utf-8")

        # Raw capture should include the full pytest output including
        # the session-starts banner and config detail.
        assert "test session starts" in raw_text
        # Progress capture should at minimum include the wrapper header
        # and the summary banner.
        assert "# watch_pytest" in progress_text
        assert re.search(r"\d+ passed", progress_text)
        assert "exit=0" in progress_text
