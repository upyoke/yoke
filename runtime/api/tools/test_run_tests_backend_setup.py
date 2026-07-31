"""Tests for how the runner prepares Postgres authority and launches pytest.

Split from the runner's argv/CLI tests so each file stays within the
authored-file line limit.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from yoke_core.tools import _source_pythonpath, run_tests


class _LaunchedPytest:
    """Stand-in for the launched pytest process group.

    The runner owns its child's process group so an interrupted run reaps its
    xdist workers; these tests care only about how it was launched, so the
    stub answers the one call the success path makes.
    """

    def __init__(self, returncode: int = 0):
        self._returncode = returncode

    def poll(self) -> int:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode


def _capture_launch(captured: dict):
    """Patch value recording how the runner launched pytest."""

    def launch(*args, **kwargs):
        captured["argv"] = args[0] if args else None
        captured["kwargs"] = kwargs
        return _LaunchedPytest()

    return launch


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
            run_tests.process_group_reaping,
            "popen_in_process_group",
            _capture_launch(captured),
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
            run_tests.process_group_reaping,
            "popen_in_process_group",
            _capture_launch(captured),
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
            run_tests.process_group_reaping,
            "popen_in_process_group",
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

        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests,
            "_prepare_yoke_backend_env",
            lambda prepared_root: calls.append(prepared_root) or True,
        )
        monkeypatch.setattr(
            run_tests.process_group_reaping,
            "popen_in_process_group",
            lambda *args, **kwargs: _LaunchedPytest(),
        )

        assert run_tests.run() == 0
        assert calls == [root.resolve()]

    def test_postgres_authority_failure_stops_before_pytest(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "yoke"
        (root / "runtime" / "api").mkdir(parents=True)
        monkeypatch.setenv("YOKE_PYTEST_WORKERS", "auto")
        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests, "_prepare_yoke_backend_env", lambda prepared_root: False
        )
        monkeypatch.setattr(
            run_tests.process_group_reaping,
            "popen_in_process_group",
            lambda *args, **kwargs: pytest.fail("pytest should not start"),
        )

        assert run_tests.run() == 1

    def test_interrupted_run_reports_the_signal_it_died_on(
        self, tmp_path: Path, monkeypatch
    ):
        """An interrupted runner reaps its workers and says how it died.

        Workers that outlive the runner keep their test databases open, so the
        guard reaps the whole group; the exit code follows the shell
        convention (130 for Ctrl-C, 143 for SIGTERM) rather than collapsing
        into a generic failure.
        """
        import signal

        from yoke_core.domain import process_group_reaping

        root = tmp_path / "yoke"
        (root / "runtime" / "api").mkdir(parents=True)
        monkeypatch.setenv("YOKE_PYTEST_WORKERS", "auto")
        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests, "_prepare_yoke_backend_env", lambda prepared_root: True
        )

        class _InterruptedLaunch(_LaunchedPytest):
            """Dies on the first wait, then behaves like a reaped child."""

            def __init__(self):
                super().__init__()
                self._interrupted = False

            def wait(self, timeout: float | None = None) -> int:
                if self._interrupted:
                    return 0
                self._interrupted = True
                raise process_group_reaping.ProcessGroupInterrupted(
                    signal.SIGTERM
                )

        monkeypatch.setattr(
            run_tests.process_group_reaping,
            "popen_in_process_group",
            lambda *args, **kwargs: _InterruptedLaunch(),
        )

        assert run_tests.run() == 128 + signal.SIGTERM

    def test_non_yoke_repo_does_not_prepare_canonical_db(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "mini"
        root.mkdir()
        calls = []

        monkeypatch.setattr(run_tests, "_repo_root", lambda: root)
        monkeypatch.setattr(
            run_tests,
            "_prepare_yoke_backend_env",
            lambda prepared_root: calls.append(prepared_root) or True,
        )
        monkeypatch.setattr(
            run_tests.process_group_reaping,
            "popen_in_process_group",
            lambda *args, **kwargs: _LaunchedPytest(),
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

