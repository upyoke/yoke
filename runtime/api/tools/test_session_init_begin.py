"""Tests for ``session_init``'s transport-keyed session-establishment path.

``_session_begin`` routes through the ``yoke sessions begin`` CLI adapter
(connection-keyed, so a prod-over-https ``/yoke do`` bootstrap relays to the
server) and ``main`` forwards the underlying handler's real message on
failure so the cause is actionable instead of an opaque exit code.
"""

from __future__ import annotations

import subprocess

from yoke_core.tools import session_init
from runtime.api.test_constants import TEST_MODEL_ID


class TestSessionBeginCommandShape:
    def test_session_begin_invokes_yoke_sessions_begin(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

        monkeypatch.setattr(session_init.subprocess, "run", fake_run)
        completed = session_init._session_begin(
            session_id="sid", executor="claude-code", provider="anthropic",
            model="m", workspace="/ws",
        )
        assert completed.returncode == 0
        cmd = captured["cmd"]
        # Transport-keyed CLI adapter, NOT the raw local service_client.
        assert cmd[:5] == [
            session_init.sys.executable, "-m", "yoke_cli.main",
            "sessions", "begin",
        ]
        assert "session-begin" not in cmd
        assert "yoke_core.api.service_client" not in cmd
        assert captured["kwargs"].get("capture_output") is True


class TestMainForwardsFailureCause:
    def _bootstrap(self, workspace, monkeypatch, session_id):
        workspace.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(workspace), check=True)
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("YOKE_SESSION_ID", session_id)
        monkeypatch.setattr(
            session_init, "_resolve_model",
            lambda session_id, executor: TEST_MODEL_ID,
        )

    def test_main_forwards_captured_stderr_on_failure(
        self, tmp_path, monkeypatch, capsys,
    ):
        self._bootstrap(tmp_path / "ws", monkeypatch, "fail-session")
        real_cause = "Session registration requires a project id."

        def fake_begin(**kwargs):
            return subprocess.CompletedProcess(
                [], 2, stdout="", stderr=real_cause + "\n",
            )

        monkeypatch.setattr(session_init, "_session_begin", fake_begin)
        rc = session_init.main([])  # NOT --skip-begin: exercise the begin path.
        assert rc == 2
        err = capsys.readouterr().err
        assert real_cause in err
        assert "session-begin failed with exit 2" in err

    def test_main_forwards_stdout_when_stderr_empty(
        self, tmp_path, monkeypatch, capsys,
    ):
        self._bootstrap(tmp_path / "ws", monkeypatch, "fail-session-2")
        failure_json = '{"success": false, "code": "SOME_CODE"}'

        def fake_begin(**kwargs):
            return subprocess.CompletedProcess(
                [], 1, stdout=failure_json + "\n", stderr="",
            )

        monkeypatch.setattr(session_init, "_session_begin", fake_begin)
        rc = session_init.main([])
        assert rc == 1
        err = capsys.readouterr().err
        assert "SOME_CODE" in err
