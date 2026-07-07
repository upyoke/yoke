"""Tests for yoke_core.domain.browser_worker.

These tests are fully hermetic — they never touch real SSH, real PIDs
other than the current process, or the machine's real browser runtime
state files. The CLI is driven via ``browser_worker.main`` and all
filesystem state is redirected into a ``tmp_path``-rooted state home
passed as the explicit ``root`` override.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from unittest import mock

from yoke_core.domain import browser_worker


def _fake_state_home(tmp: Path) -> Path:
    root = tmp / "state_home"
    root.mkdir(parents=True)
    return root


def _install_capability_mock(
    monkeypatch: Any, responder: Any
) -> List[str]:
    """Patch ``projects.list_capability_settings_by_type`` so tests never hit the DB.

    ``responder`` takes the requested capability type and returns either a
    list of raw settings JSON strings (success) or raises ``RuntimeError``
    to simulate a DB error. The second element of the returned tuple on
    the old ``_run_yoke_db`` contract (``(rc, out)``) maps to either a
    list or an exception here.
    """
    from yoke_core.domain import projects as _projects

    calls: List[str] = []

    def fake_list_by_type(cap_type):
        calls.append(cap_type)
        result = responder(cap_type)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        _projects, "list_capability_settings_by_type", fake_list_by_type
    )
    return calls


class _MonkeyPatch:
    """Tiny pytest-style monkeypatch shim so this file runs under unittest."""

    def __init__(self) -> None:
        self._undo: List[Any] = []

    def setattr(self, target: Any, name: str, value: Any) -> None:
        orig = getattr(target, name)
        setattr(target, name, value)
        self._undo.append((target, name, orig))

    def undo(self) -> None:
        while self._undo:
            target, name, orig = self._undo.pop()
            setattr(target, name, orig)


class BrowserWorkerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self._make_tmpdir())
        self.repo = _fake_state_home(self.tmp)
        self.mp = _MonkeyPatch()

    def tearDown(self) -> None:
        self.mp.undo()

    def _make_tmpdir(self) -> str:
        import tempfile

        d = tempfile.mkdtemp(prefix="yoke-browser-worker-")
        self.addCleanup(self._rmtree, d)
        return d

    def _rmtree(self, path: str) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------------
    # Usage + argument validation
    # ------------------------------------------------------------------

    def test_no_args_exits_usage(self) -> None:
        self.assertEqual(browser_worker.main([]), browser_worker.EXIT_USAGE)

    def test_unknown_command_exits_usage(self) -> None:
        self.assertEqual(
            browser_worker.main(["foobar"]), browser_worker.EXIT_USAGE
        )

    def test_start_without_host_is_usage(self) -> None:
        self.assertEqual(
            browser_worker.main(["start"]), browser_worker.EXIT_USAGE
        )

    def test_stop_without_host_is_usage(self) -> None:
        self.assertEqual(
            browser_worker.main(["stop"]), browser_worker.EXIT_USAGE
        )

    def test_status_without_host_is_usage(self) -> None:
        self.assertEqual(
            browser_worker.main(["status"]), browser_worker.EXIT_USAGE
        )

    def test_start_unknown_option_is_usage(self) -> None:
        self.assertEqual(
            browser_worker.main(["start", "h", "--nope", "1"]),
            browser_worker.EXIT_USAGE,
        )

    # ------------------------------------------------------------------
    # Tunnel PID file + liveness helpers
    # ------------------------------------------------------------------

    def test_tunnel_pid_file_lifecycle(self) -> None:
        path = browser_worker._tunnel_pid_file(self.repo)
        browser_worker._write_tunnel_pid(12345, self.repo)
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(), "12345")
        browser_worker._remove_tunnel_pid(self.repo)
        self.assertFalse(path.is_file())

    def test_cleanup_stale_tunnel_removes_dead_pid(self) -> None:
        browser_worker._write_tunnel_pid(99999, self.repo)
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: False)
        browser_worker._cleanup_stale_tunnel(self.repo)
        self.assertFalse(browser_worker._tunnel_pid_file(self.repo).is_file())

    def test_cleanup_stale_tunnel_keeps_live_pid(self) -> None:
        browser_worker._write_tunnel_pid(os.getpid(), self.repo)
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: True)
        browser_worker._cleanup_stale_tunnel(self.repo)
        self.assertTrue(browser_worker._tunnel_pid_file(self.repo).is_file())

    # ------------------------------------------------------------------
    # State file helpers
    # ------------------------------------------------------------------

    def test_local_daemon_running_detects_live_healthy_pid(self) -> None:
        browser_worker._write_state(
            {"pid": os.getpid(), "health": "healthy"}, self.repo
        )
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: True)
        self.assertTrue(browser_worker._local_daemon_running(self.repo))

    def test_local_daemon_running_ignores_dead_pid(self) -> None:
        browser_worker._write_state(
            {"pid": 99999, "health": "healthy"}, self.repo
        )
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: False)
        self.assertFalse(browser_worker._local_daemon_running(self.repo))

    def test_local_daemon_running_ignores_crashed_health(self) -> None:
        browser_worker._write_state(
            {"pid": os.getpid(), "health": "crashed"}, self.repo
        )
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: True)
        self.assertFalse(browser_worker._local_daemon_running(self.repo))

    # ------------------------------------------------------------------
    # Remote config lookup
    # ------------------------------------------------------------------

    def test_lookup_remote_config_finds_matching_host(self) -> None:
        row = (
            '{"host": "build-server.local", "user": "deploy",'
            ' "key_path": "/k", "browser_path": "/b", "port": 9222}'
        )
        _install_capability_mock(self.mp, lambda _t: [row])
        cfg = browser_worker.lookup_remote_config(
            "build-server.local", root=self.repo
        )
        assert cfg is not None
        self.assertEqual(cfg.user, "deploy")
        self.assertEqual(cfg.key_path, "/k")
        self.assertEqual(cfg.browser_path, "/b")
        self.assertEqual(cfg.port, 9222)

    def test_lookup_remote_config_returns_none_for_unknown_host(self) -> None:
        row = '{"host": "other", "user": "u", "port": 9222}'
        _install_capability_mock(self.mp, lambda _t: [row])
        self.assertIsNone(
            browser_worker.lookup_remote_config("missing", root=self.repo)
        )

    def test_lookup_remote_config_handles_empty_result(self) -> None:
        _install_capability_mock(self.mp, lambda _t: [])
        self.assertIsNone(
            browser_worker.lookup_remote_config("anything", root=self.repo)
        )

    def test_lookup_remote_config_handles_error(self) -> None:
        _install_capability_mock(self.mp, lambda _t: RuntimeError("db broken"))
        self.assertIsNone(
            browser_worker.lookup_remote_config("h", root=self.repo)
        )

    # ------------------------------------------------------------------
    # start command — guard paths (no real SSH involved)
    # ------------------------------------------------------------------

    def test_start_refuses_when_local_daemon_running(self) -> None:
        browser_worker._write_state(
            {"pid": os.getpid(), "health": "healthy"}, self.repo
        )
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: True)
        rc = browser_worker.cmd_start("build-server.local", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_FAIL)

    def test_start_cleans_up_stale_tunnel_then_proceeds_until_ssh(self) -> None:
        browser_worker._write_tunnel_pid(99999, self.repo)
        # First _pid_alive call is for the state file daemon (none), second
        # is for the tunnel PID file — both reported dead.
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: False)
        _install_capability_mock(
            self.mp,
            lambda _t: ['{"host": "h1", "user": "u", "port": 9222}'],
        )

        def raise_timeout(*_a, **_kw):
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=1)

        self.mp.setattr(browser_worker.subprocess, "run", raise_timeout)
        rc = browser_worker.cmd_start("h1", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_FAIL)
        # Stale tunnel PID file was removed before SSH ever ran.
        self.assertFalse(browser_worker._tunnel_pid_file(self.repo).is_file())

    def test_start_fails_cleanly_on_missing_remote_config(self) -> None:
        _install_capability_mock(self.mp, lambda _t: [])
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: False)
        rc = browser_worker.cmd_start("nowhere.local", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_FAIL)

    # ------------------------------------------------------------------
    # stop command
    # ------------------------------------------------------------------

    def test_stop_removes_state_and_tunnel_files(self) -> None:
        browser_worker._write_tunnel_pid(99999, self.repo)
        browser_worker._write_state(
            {"pid": 99999, "health": "healthy"}, self.repo
        )
        # Dead tunnel PID — skip kill.
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: False)
        # Remote config lookup returns None so no SSH is attempted.
        _install_capability_mock(self.mp, lambda _t: [])

        rc = browser_worker.cmd_stop("build-server.local", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_OK)
        self.assertFalse(browser_worker._tunnel_pid_file(self.repo).is_file())
        self.assertFalse(browser_worker._state_file(self.repo).is_file())

    # ------------------------------------------------------------------
    # status command
    # ------------------------------------------------------------------

    def test_status_nothing_running_exits_not_running(self) -> None:
        rc = browser_worker.cmd_status("somehost", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_NOT_RUNNING)

    def test_status_stale_tunnel_is_failure(self) -> None:
        browser_worker._write_tunnel_pid(99999, self.repo)
        browser_worker._write_state(
            {"pid": 99999, "health": "healthy", "endpoint": "http://x"},
            self.repo,
        )
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: False)
        rc = browser_worker.cmd_status("somehost", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_FAIL)

    def test_status_alive_tunnel_and_reachable(self) -> None:
        browser_worker._write_tunnel_pid(os.getpid(), self.repo)
        browser_worker._write_state(
            {
                "pid": os.getpid(),
                "health": "healthy",
                "endpoint": "http://localhost:19222",
            },
            self.repo,
        )
        self.mp.setattr(browser_worker, "_pid_alive", lambda pid: True)

        class _Ok:
            returncode = 0

        self.mp.setattr(
            browser_worker.subprocess, "run", lambda *a, **kw: _Ok()
        )
        rc = browser_worker.cmd_status("somehost", root=self.repo)
        self.assertEqual(rc, browser_worker.EXIT_OK)

    # ------------------------------------------------------------------
    # SSH argv shapes (pure, no subprocess)
    # ------------------------------------------------------------------

    def test_ssh_argv_includes_key_when_present(self) -> None:
        cfg = browser_worker.RemoteConfig(
            host="h", user="u", key_path="/k", browser_path="/b", port=9222
        )
        argv = browser_worker._ssh_exec(cfg, "echo ok")
        self.assertIn("-i", argv)
        self.assertIn("/k", argv)
        self.assertEqual(argv[-1], "echo ok")

    def test_ssh_tunnel_argv_shape(self) -> None:
        cfg = browser_worker.RemoteConfig(
            host="h", user="u", key_path="", browser_path="/b", port=9222
        )
        argv = browser_worker._ssh_tunnel_argv(
            cfg, local_port=19222, remote_port=9222
        )
        self.assertIn("-f", argv)
        self.assertIn("-N", argv)
        self.assertIn("-L", argv)
        self.assertIn("19222:127.0.0.1:9222", argv)


if __name__ == "__main__":
    unittest.main()
