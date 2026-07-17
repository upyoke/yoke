"""Tests for ``yoke_core.tools.run_tests`` — the generic runner contract.

These cover argv construction, CLI parsing, and a live subprocess smoke to
confirm the runner actually drives pytest end-to-end.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH
from yoke_core.tools import _source_pythonpath, run_tests


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
        ns = run_tests._parse_args([])
        assert ns.paths == []
        assert ns.keyword is None
        assert ns.fail_fast is False
        assert ns.quiet is False
        assert ns.list_only is False

    def test_keyword_flag(self):
        ns = run_tests._parse_args(["-k", "feed"])
        assert ns.keyword == "feed"

    def test_paths_accumulate(self):
        ns = run_tests._parse_args(
            ["runtime/api/test_items_query.py", "runtime/api/test_api.py"]
        )
        assert ns.paths == [
            "runtime/api/test_items_query.py",
            "runtime/api/test_api.py",
        ]

    def test_fail_fast_short_and_long(self):
        ns = run_tests._parse_args(["-x"])
        assert ns.fail_fast is True
        ns = run_tests._parse_args(["--fail-fast"])
        assert ns.fail_fast is True

    def test_list_flag(self):
        ns = run_tests._parse_args(["--list"])
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
# Canonical Yoke DB setup before backend verification.
# ---------------------------------------------------------------------------


class TestCanonicalYokeDbSetup:
    def test_run_tests_passes_local_postgres_auto_worker_env(
        self, tmp_path: Path, monkeypatch
    ):
        (root := tmp_path / "yoke").joinpath("runtime", "api").mkdir(parents=True)
        captured = {}

        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests, "_prepare_yoke_backend_env", lambda prepared_root: True
        )
        monkeypatch.setattr(
            run_tests.subprocess,
            "run",
            lambda *args, **kwargs: captured.update(kwargs=kwargs)
            or subprocess.CompletedProcess(args[0], 0),
        )
        assert run_tests.run(["runtime/api/tools"], extra=["-n", "auto"]) == 0

        env = captured["kwargs"]["env"]
        assert env["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "10"

    def test_run_tests_prepends_checkout_package_sources(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "yoke"
        (root / "runtime" / "api").mkdir(parents=True)
        (root / "packages" / "yoke-core" / "src" / "yoke_core").mkdir(
            parents=True
        )
        captured = {}

        monkeypatch.setenv("PYTHONPATH", "/already/there")
        monkeypatch.setenv("YOKE_PYTEST_WORKERS", "auto")
        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests, "_prepare_yoke_backend_env", lambda prepared_root: True
        )
        monkeypatch.setattr(
            run_tests._source_pythonpath,
            "import_origin_refusal",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            run_tests.subprocess,
            "run",
            lambda *args, **kwargs: captured.update(kwargs=kwargs)
            or subprocess.CompletedProcess(args[0], 0),
        )

        assert run_tests.run(["runtime/api/tools"], extra=["-n", "auto"]) == 0
        env_entries = captured["kwargs"]["env"]["PYTHONPATH"].split(os.pathsep)
        assert env_entries[: len(_source_pythonpath.PACKAGE_SRC_RELS)] == [
            str((root / rel).resolve())
            for rel in _source_pythonpath.PACKAGE_SRC_RELS
        ]
        assert str(root.resolve()) in env_entries
        assert "/already/there" in env_entries

    def test_run_tests_refuses_wrong_checkout_import_origin(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        root = tmp_path / "yoke"
        (root / "runtime" / "api").mkdir(parents=True)
        (root / "packages" / "yoke-core" / "src" / "yoke_core").mkdir(
            parents=True
        )

        monkeypatch.setenv("YOKE_PYTEST_WORKERS", "auto")
        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests, "_prepare_yoke_backend_env", lambda prepared_root: True
        )
        monkeypatch.setattr(
            run_tests._source_pythonpath,
            "import_origin_refusal",
            lambda *args, **kwargs: "yoke_core import origin is outside",
        )
        monkeypatch.setattr(
            run_tests.subprocess,
            "run",
            lambda *args, **kwargs: pytest.fail("pytest should not start"),
        )

        assert run_tests.run(["runtime/api/tools"], extra=["-n", "auto"]) == 1
        assert "import origin is outside" in capsys.readouterr().err

    def test_default_yoke_backend_run_prepares_postgres_authority(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "yoke"
        (root / "runtime" / "api").mkdir(parents=True)
        calls = []

        class Completed:
            returncode = 0
            # ``stdout`` is read by the RAM-aware ``-n`` worker selector via
            # ``subprocess.run(["vm_stat"], capture_output=True)``; an empty
            # string makes ``_read_free_ram_mb`` fall through to its
            # high-capacity default without affecting the pytest call below.
            stdout = ""

        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests,
            "_prepare_yoke_backend_env",
            lambda prepared_root: calls.append(prepared_root) or True,
        )
        monkeypatch.setattr(
            run_tests.subprocess,
            "run",
            lambda *args, **kwargs: Completed(),
        )

        assert run_tests.run() == 0
        assert calls == [root.resolve()]

    def test_postgres_authority_failure_stops_before_pytest(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "yoke"
        (root / "runtime" / "api").mkdir(parents=True)
        # Short-circuit the RAM-aware worker selector so its ``vm_stat``
        # subprocess.run call does not race the pytest-shaped one we are
        # asserting against below.
        monkeypatch.setenv("YOKE_PYTEST_WORKERS", "auto")
        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests, "_prepare_yoke_backend_env", lambda prepared_root: False
        )
        monkeypatch.setattr(
            run_tests.subprocess,
            "run",
            lambda *args, **kwargs: pytest.fail("pytest should not start"),
        )

        assert run_tests.run() == 1

    def test_non_yoke_repo_does_not_prepare_canonical_db(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "mini"
        root.mkdir()
        calls = []

        class Completed:
            returncode = 0
            # See ``test_default_yoke_backend_run_prepares_canonical_db``
            # for why ``stdout`` matters here.
            stdout = ""

        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests,
            "_prepare_yoke_backend_env",
            lambda prepared_root: calls.append(prepared_root) or True,
        )
        monkeypatch.setattr(
            run_tests.subprocess,
            "run",
            lambda *args, **kwargs: Completed(),
        )

        assert run_tests.run(["pkgx"]) == 0
        assert calls == []

    def test_prepare_failure_names_root_resolver_and_recovery(
        self, tmp_path: Path, monkeypatch
    ):
        def _boom():
            raise RuntimeError("no postgres binding")

        from yoke_core.domain import db_backend

        monkeypatch.setattr(db_backend, "resolve_pg_dsn", _boom)
        stderr = io.StringIO()

        assert run_tests._prepare_yoke_backend_env(tmp_path, stderr=stderr) is False
        message = stderr.getvalue()
        assert str(tmp_path) in message
        assert "YOKE_PG_DSN" in message
        assert "connected-env" in message


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


class TestLiveSmoke:
    def test_runner_cli_runs_and_passes(self, mini_repo: Path):
        """Invoke the runner as a subprocess against the mini repo."""
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{SOURCE_PYTHONPATH}{os.pathsep}{mini_repo}"
            f"{os.pathsep}{env.get('PYTHONPATH', '')}"
        )
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.tools.run_tests", "pkgx"],
            cwd=str(mini_repo),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"runner failed (exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "2 passed" in result.stdout or "2 passed" in result.stderr

    def test_runner_cli_list_mode(self, mini_repo: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{SOURCE_PYTHONPATH}{os.pathsep}{mini_repo}"
            f"{os.pathsep}{env.get('PYTHONPATH', '')}"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yoke_core.tools.run_tests",
                "--list",
                "pkgx",
            ],
            cwd=str(mini_repo),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Collected node IDs should appear in output
        assert "test_one" in result.stdout
        assert "test_two" in result.stdout

    def test_runner_cli_keyword_filter(self, mini_repo: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{SOURCE_PYTHONPATH}{os.pathsep}{mini_repo}"
            f"{os.pathsep}{env.get('PYTHONPATH', '')}"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yoke_core.tools.run_tests",
                "-k",
                "test_one",
                "pkgx",
            ],
            cwd=str(mini_repo),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Only one test should run when filtered
        assert "1 passed" in result.stdout or "1 passed" in result.stderr
