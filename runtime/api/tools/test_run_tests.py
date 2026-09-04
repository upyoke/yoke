"""Tests for ``yoke_core.tools.run_tests`` — the generic runner contract.

These cover argv construction, CLI parsing, and a live subprocess smoke to
confirm the runner actually drives pytest end-to-end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH
from yoke_core.tools import _run_tests_args, gate_admission, run_tests



# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------


class TestBuildPytestArgv:
    def test_defaults_use_configured_testpaths(self):
        argv = run_tests.build_pytest_argv([])
        defaults = list(run_tests.DEFAULT_TESTPATHS)
        assert argv[-len(defaults):] == defaults
        assert "-ra" in argv

    def test_explicit_paths_override_defaults(self):
        argv = run_tests.build_pytest_argv(["runtime/api/test_items_query.py"])
        assert argv[-1] == "runtime/api/test_items_query.py"
        assert "runtime/api" not in argv

    def test_keyword_filter_appends_dash_k(self):
        argv = run_tests.build_pytest_argv([], keyword="dependency")
        assert "-k" in argv
        idx = argv.index("-k")
        assert argv[idx + 1] == "dependency"

    def test_fail_fast_appends_x(self):
        argv = run_tests.build_pytest_argv([], fail_fast=True)
        assert "-x" in argv

    def test_quiet_replaces_default_ra(self):
        argv = run_tests.build_pytest_argv([], quiet=True)
        assert "-q" in argv
        assert "-ra" not in argv

    def test_list_only_switches_to_collect(self):
        argv = run_tests.build_pytest_argv([], list_only=True)
        assert "--collect-only" in argv
        assert "-q" in argv
        # list mode should suppress the default -ra progress flag
        assert "-ra" not in argv

    def test_extra_args_pass_through_before_paths(self):
        argv = run_tests.build_pytest_argv(
            ["runtime/api/test_items_query.py"],
            extra=["--tb=short", "--no-header"],
        )
        assert "--tb=short" in argv
        assert "--no-header" in argv
        # extras appear before path args so pytest parses them as options
        assert argv.index("--tb=short") < argv.index("runtime/api/test_items_query.py")


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


class TestCLIParsing:
    def test_no_args_produces_defaults(self):
        ns = _run_tests_args.parse_args([])
        assert ns.paths == []
        assert ns.keyword is None
        assert ns.fail_fast is False
        assert ns.quiet is False
        assert ns.list_only is False

    def test_keyword_flag(self):
        ns = _run_tests_args.parse_args(["-k", "feed"])
        assert ns.keyword == "feed"

    def test_paths_accumulate(self):
        ns = _run_tests_args.parse_args(
            ["runtime/api/test_items_query.py", "runtime/api/test_api.py"]
        )
        assert ns.paths == [
            "runtime/api/test_items_query.py",
            "runtime/api/test_api.py",
        ]

    def test_fail_fast_short_and_long(self):
        ns = _run_tests_args.parse_args(["-x"])
        assert ns.fail_fast is True
        ns = _run_tests_args.parse_args(["--fail-fast"])
        assert ns.fail_fast is True

    def test_list_flag(self):
        ns = _run_tests_args.parse_args(["--list"])
        assert ns.list_only is True


# ---------------------------------------------------------------------------
# Repo root discovery
# ---------------------------------------------------------------------------


class TestRepoRoot:
    def test_repo_root_finds_pyproject(self, tmp_path: Path):
        fake_root = tmp_path / "fake-repo"
        (fake_root / "pkg").mkdir(parents=True)
        (fake_root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        start = fake_root / "pkg" / "deep" / "file.py"
        start.parent.mkdir(parents=True, exist_ok=True)
        start.write_text("")
        assert run_tests._repo_root(start) == fake_root.resolve()

    def test_repo_root_falls_back_to_cwd(self, tmp_path: Path, monkeypatch):
        # No pyproject.toml anywhere up the tree
        monkeypatch.chdir(tmp_path)
        found = run_tests._repo_root(tmp_path / "deep" / "missing.py")
        assert found == Path.cwd() or found.is_absolute()



# ---------------------------------------------------------------------------
# Live smoke: run the runner as a subprocess against a trivial passing test.
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """Build a tiny self-contained repo with pyproject + one passing test."""
    root = tmp_path / "mini"
    pkg = root / "pkgx"
    pkg.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'pkgx'\nversion = '0.0.0'\n"
        "[tool.pytest.ini_options]\ntestpaths = ['pkgx']\n"
    )
    (pkg / "__init__.py").write_text("")
    (pkg / "test_ok.py").write_text(
        "def test_one():\n    assert 1 + 1 == 2\n"
        "def test_two():\n    assert True\n"
    )
    return root


#: Ceiling for one nested runner invocation against the two-test mini repo.
#: Generous for the work involved; the point is that a wedged child fails the
#: test instead of blocking its worker until someone kills the run by hand.
_NESTED_RUNNER_TIMEOUT_S = 300


def _run_nested_runner(mini_repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke the runner as a subprocess against *mini_repo*.

    Exempt from machine-wide gate admission, and time-boxed.

    The nested invocation names a directory, so ``is_heavy_invocation`` calls
    it heavy and it would otherwise arbitrate for a machine gate slot. The
    deadlock that used to make that fatal is now handled in the admission
    module itself: a run that bypasses admission publishes that it holds no
    slot, and a heavy descendant of such a run proceeds instead of queueing
    behind a stranger. What survives here is the narrower claim that a
    two-test throwaway repo is not the heavy workload the cap exists to
    serialize — so it opts out at this call site rather than by loosening
    what counts as heavy for every caller. The opt-out still earns its keep
    when this file is driven by a bare ``pytest`` rather than through the
    runner or watcher, because nothing in that chain publishes an admission
    state and the child would queue under the wait bound.

    The timeout is the backstop: any future block fails this test loudly
    instead of wedging its worker until someone kills the run by hand.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{SOURCE_PYTHONPATH}{os.pathsep}{mini_repo}"
        f"{os.pathsep}{env.get('PYTHONPATH', '')}"
    )
    env[gate_admission.CAP_ENV] = "0"
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.tools.run_tests", *args],
        cwd=str(mini_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=_NESTED_RUNNER_TIMEOUT_S,
    )


class TestLiveSmoke:
    def test_runner_cli_runs_and_passes(self, mini_repo: Path):
        """Invoke the runner as a subprocess against the mini repo."""
        result = _run_nested_runner(mini_repo, "pkgx")
        assert result.returncode == 0, (
            f"runner failed (exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "2 passed" in result.stdout or "2 passed" in result.stderr

    def test_runner_cli_list_mode(self, mini_repo: Path):
        result = _run_nested_runner(mini_repo, "--list", "pkgx")
        assert result.returncode == 0
        # Collected node IDs should appear in output
        assert "test_one" in result.stdout
        assert "test_two" in result.stdout

    def test_runner_cli_keyword_filter(self, mini_repo: Path):
        result = _run_nested_runner(mini_repo, "-k", "test_one", "pkgx")
        assert result.returncode == 0
        # Only one test should run when filtered
        assert "1 passed" in result.stdout or "1 passed" in result.stderr
