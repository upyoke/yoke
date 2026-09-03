"""Tests for the detached ``yoke ui`` daemon: custody, lifecycle, launchd.

The end-to-end case runs a real detached child that binds the port and
publishes the daemon record, because the acceptance this daemon exists
for — the view keeps serving after the terminal that started it is gone
— is not observable against a stubbed process. The launchd half is
stubbed at the boundary the engine already owns, so no test touches the
operator's login domain.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config import universe_ui_launchd as launchd
from yoke_cli.config import universe_ui_daemon_state as state


CHILD_SCRIPT = """
import socket, sys, time
from yoke_cli.config import universe_ui_daemon as daemon
host, port, env = sys.argv[1], int(sys.argv[2]), sys.argv[3]
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind((host, port))
listener.listen(8)
daemon.publish_serving_identity(host=host, port=port, env=env)
while True:
    time.sleep(0.2)
"""


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestTokenCustody:
    def test_token_is_minted_once_and_reused(self, machine_home):
        first = state.stable_session_token()
        assert first
        assert state.stable_session_token() == first

    def test_token_file_is_owner_only(self, machine_home):
        state.stable_session_token()
        mode = state.token_path().stat().st_mode & 0o777
        assert mode == 0o600

    def test_token_survives_a_down_cycle(self, machine_home):
        minted = state.stable_session_token()
        daemon.down()
        assert state.token_path().is_file()
        assert state.stable_session_token() == minted

    def test_record_never_carries_the_token(self, machine_home):
        token = state.stable_session_token()
        state.write_record(
            pid=os.getpid(), host="127.0.0.1", port=8688,
            env="local", supervised=False,
        )
        document = state.record_path().read_text(encoding="utf-8")
        assert token not in document
        assert json.loads(document)["pid"] == os.getpid()


class TestStatus:
    def test_no_record_reports_stopped(self, machine_home):
        report = daemon.status()
        assert report["running"] is False
        assert "private_url" not in report

    def test_dead_pid_clears_the_stale_record(self, machine_home):
        dead = _dead_pid()
        state.write_record(
            pid=dead, host="127.0.0.1", port=8688,
            env="local", supervised=False,
        )
        report = daemon.status()
        assert report["running"] is False
        assert report["cleared_stale_record_for_pid"] == dead
        assert not state.record_path().exists()

    def test_live_record_reports_the_tokened_url(self, machine_home):
        state.write_record(
            pid=os.getpid(), host="127.0.0.1", port=8688,
            env="local", supervised=False,
        )
        report = daemon.status()
        assert report["running"] is True
        assert report["env"] == "local"
        assert report["private_url"].endswith(state.stable_session_token())
        assert report["private_url"].startswith("http://127.0.0.1:8688/?token=")


class TestDetachedLifecycle:
    @pytest.fixture(autouse=True)
    def unsupervised(self, monkeypatch):
        monkeypatch.setattr(launchd, "supported", lambda: False)
        monkeypatch.setattr(launchd, "agent_installed", lambda: False)

    def test_up_returns_with_the_port_serving_then_down_stops_it(
        self, monkeypatch, machine_home,
    ):
        port = _free_port()
        monkeypatch.setattr(
            launchd, "child_command",
            lambda *, host, port, env: [
                sys.executable, "-c", CHILD_SCRIPT, host, str(port), env,
            ],
        )

        started = daemon.up(host="127.0.0.1", port=port, env="local")
        try:
            assert started["started"] is True
            assert started["running"] is True
            assert started["serving"] is True
            assert state.port_accepting("127.0.0.1", port) is True
            assert daemon.status()["pid"] == started["pid"]
            assert started["private_url"].endswith(
                state.stable_session_token(),
            )
        finally:
            stopped = daemon.down()

        assert stopped["stopped"] is True
        assert stopped["stopped_pid"] == started["pid"]
        assert not state.record_path().exists()
        assert state.port_accepting("127.0.0.1", port) is False

    def test_up_is_idempotent_while_the_daemon_serves(
        self, monkeypatch, machine_home,
    ):
        port = _free_port()
        monkeypatch.setattr(
            launchd, "child_command",
            lambda *, host, port, env: [
                sys.executable, "-c", CHILD_SCRIPT, host, str(port), env,
            ],
        )
        first = daemon.up(host="127.0.0.1", port=port, env="local")
        try:
            again = daemon.up(host="127.0.0.1", port=port, env="local")
            assert again["started"] is False
            assert again["pid"] == first["pid"]
        finally:
            daemon.down()

    def test_a_child_that_never_serves_refuses_and_leaves_nothing(
        self, monkeypatch, machine_home,
    ):
        monkeypatch.setattr(daemon, "READY_TIMEOUT_S", 1.0)
        monkeypatch.setattr(
            launchd, "child_command",
            lambda *, host, port, env: [
                sys.executable, "-c", "raise SystemExit('no universe here')",
            ],
        )
        with pytest.raises(state.UiDaemonError) as refusal:
            daemon.up(host="127.0.0.1", port=_free_port(), env="local")
        message = str(refusal.value)
        assert "did not begin serving" in message
        assert str(state.log_path()) in message
        assert "no universe here" in message
        assert not state.record_path().exists()

    def test_down_on_a_stopped_daemon_is_not_an_error(self, machine_home):
        report = daemon.down()
        assert report["running"] is False
        assert report["stopped"] is False


class TestLaunchdSupervision:
    def test_up_registers_the_agent_when_launchd_supervises(
        self, monkeypatch, machine_home,
    ):
        installs: list = []
        monkeypatch.setattr(launchd, "supported", lambda: True)
        monkeypatch.setattr(launchd, "agent_installed", lambda: True)
        monkeypatch.setattr(
            launchd, "install_agent",
            lambda **kwargs: installs.append(kwargs),
        )

        def publish_then_ready(*, host, port):
            state.write_record(
                pid=os.getpid(), host=host, port=port,
                env="local", supervised=True,
            )
            return state.read_record()

        monkeypatch.setattr(daemon, "_await_ready", publish_then_ready)
        report = daemon.up(host="127.0.0.1", port=8688, env="local")
        assert report["supervised_by_launchd"] is True
        assert installs[0]["host"] == "127.0.0.1"
        assert installs[0]["port"] == 8688
        assert installs[0]["env"] == "local"
        assert installs[0]["log_path"] == state.log_path()

    def test_down_removes_the_agent_before_stopping(
        self, monkeypatch, machine_home,
    ):
        removals: list = []
        monkeypatch.setattr(
            launchd, "remove_agent",
            lambda: (removals.append("removed"), True)[1],
        )
        report = daemon.down()
        assert removals == ["removed"]
        assert report["removed_launchd_agent"] is True

    def test_plist_keeps_the_view_alive_across_login(
        self, monkeypatch, machine_home,
    ):
        monkeypatch.setattr(
            launchd, "_shim_path", lambda environ=None: Path("/usr/local/bin/yoke"),
        )
        document = launchd.plist_document(
            host="127.0.0.1", port=8688, env="local",
            log_path=Path("/tmp/ui.log"),
        )
        assert document["Label"] == launchd.UI_LAUNCHD_LABEL
        assert document["RunAtLoad"] is True
        assert document["KeepAlive"] is True
        assert document["ProgramArguments"] == [
            "/usr/local/bin/yoke", "--env", "local",
            "ui", "serve-process", "--host", "127.0.0.1", "--port", "8688",
        ]

    def test_child_argv_never_carries_the_session_token(
        self, monkeypatch, machine_home,
    ):
        token = state.stable_session_token()
        monkeypatch.setattr(
            launchd, "_shim_path", lambda environ=None: Path("/usr/local/bin/yoke"),
        )
        command = launchd.child_command(host="127.0.0.1", port=8688, env="local")
        assert token not in " ".join(command)

    def test_child_environment_pins_env_and_machine_home(
        self, machine_home,
    ):
        environment = launchd.child_environment("local")
        assert environment["YOKE_ENV"] == "local"
        assert environment["YOKE_MACHINE_HOME"] == str(machine_home)

    def test_launchd_support_follows_the_platform(self, monkeypatch):
        monkeypatch.setattr(launchd.sys, "platform", "darwin")
        assert launchd.supported() is True
        monkeypatch.setattr(launchd.sys, "platform", "linux")
        assert launchd.supported() is False
        assert launchd.agent_installed() is False
        assert launchd.remove_agent() is False


def _dead_pid() -> int:
    """A pid that has certainly exited: a child spawned, waited, and reaped."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid
