"""Start, stop, and serving-child behavior for ``yoke ui``.

The daemon lifecycle itself is covered against a real detached child in
``test_yoke_universe_ui_daemon.py``; these tests pin what the commands
do around it — what they hand the daemon, what they print, when they
open a browser, and that a serving daemon is never restarted from under
the operator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.universe_ui_command_test_support import (
    running_report,
    stub_server,
    write_local_connection,
)
from yoke_cli.commands import universe_ui as commands
from yoke_cli.commands import universe_ui_connection as connection
from yoke_cli.commands import universe_ui_serve as serve


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


class TestUp:
    @pytest.fixture(autouse=True)
    def local_connection(self, machine_home):
        write_local_connection()

    def test_up_starts_the_daemon_and_reports_the_door(
        self, monkeypatch, capsys,
    ):
        started: dict = {}
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server({}))
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})

        def fake_up(*, host, port, env):
            started.update({"host": host, "port": port, "env": env})
            return {**running_report(port), "started": True}

        monkeypatch.setattr(commands.daemon, "up", fake_up)

        assert commands.ui_up(["--no-browser", "--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["started"] is True
        assert report["browser_opened"] is False
        assert report["private_url"] == "http://127.0.0.1:9999/?token=stub-token"
        assert started == {"host": "127.0.0.1", "port": 9999, "env": "local"}

    def test_up_on_a_serving_daemon_reports_it_without_restarting(
        self, monkeypatch, capsys,
    ):
        monkeypatch.setattr(commands.daemon, "status", running_report)

        def refuse_start(**_kwargs):
            raise AssertionError("a serving daemon must not be restarted")

        monkeypatch.setattr(commands.daemon, "up", refuse_start)

        assert commands.ui_up(["--no-browser", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["started"] is False

    def test_explicit_host_and_port_pass_through(self, monkeypatch, capsys):
        started: dict = {}
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server({}))
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})

        def fake_up(*, host, port, env):
            started.update({"host": host, "port": port})
            return {**running_report(port), "started": True}

        monkeypatch.setattr(commands.daemon, "up", fake_up)

        assert commands.ui_up([
            "--host", "localhost", "--port", "8123", "--no-browser", "--json",
        ]) == 0
        assert started == {"host": "localhost", "port": 8123}

    def test_remote_host_is_refused(self, monkeypatch, capsys):
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server({}))
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})

        assert commands.ui_up(["--host", "0.0.0.0", "--no-browser"]) == 1
        assert "loopback-only" in capsys.readouterr().err

    def test_busy_port_refusal_names_the_flag(self, monkeypatch, capsys):
        monkeypatch.setattr(
            connection, "ui_server", lambda: stub_server({}, busy_port=True),
        )
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})

        assert commands.ui_up(["--no-browser"]) == 1
        assert "--port" in capsys.readouterr().err

    def test_the_browser_opens_on_the_tokened_url_by_default(
        self, monkeypatch, capsys,
    ):
        opened: list = []
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server({}))
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})
        monkeypatch.setattr(
            commands.daemon, "up",
            lambda **_kwargs: {**running_report(), "started": True},
        )
        monkeypatch.setattr(commands.webbrowser, "open", opened.append)

        assert commands.ui_up(["--json"]) == 0
        assert opened == ["http://127.0.0.1:9999/?token=stub-token"]


class TestDown:
    def test_down_reports_the_stopped_pid(
        self, monkeypatch, machine_home, capsys,
    ):
        monkeypatch.setattr(
            commands.daemon, "down",
            lambda: {"running": False, "stopped": True, "stopped_pid": 4242},
        )
        assert commands.ui_down([]) == 0
        assert "stopped (pid 4242)" in capsys.readouterr().out

    def test_down_on_a_stopped_daemon_says_so(
        self, monkeypatch, machine_home, capsys,
    ):
        monkeypatch.setattr(
            commands.daemon, "down",
            lambda: {"running": False, "stopped": False},
        )
        assert commands.ui_down(["--json"]) == 0
        assert json.loads(capsys.readouterr().out)["stopped"] is False


class TestServeProcess:
    def test_the_child_serves_the_stable_token_and_publishes_itself(
        self, monkeypatch, machine_home, capsys,
    ):
        write_local_connection()
        record: dict = {}
        published: dict = {}
        monkeypatch.setattr(connection, "converge_universe_schema", lambda: None)
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server(record))
        monkeypatch.setattr(
            serve.daemon, "publish_serving_identity",
            lambda **kwargs: published.update(kwargs),
        )
        monkeypatch.setattr(
            serve.daemon, "retract_serving_identity", lambda: None,
        )

        assert serve.ui_serve_process([]) == 0
        assert record["served"]["token"] == serve.stable_session_token()
        assert record["served"]["open_browser"] is False
        assert published == {"host": "127.0.0.1", "port": 9999, "env": "local"}

    def test_converge_failure_refuses_and_never_serves(
        self, monkeypatch, machine_home, capsys,
    ):
        write_local_connection()
        record: dict = {}

        def broken_converge():
            raise ValueError("relation catalog is unreachable")

        monkeypatch.setattr(connection, "converge_universe_schema", broken_converge)
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server(record))

        assert serve.ui_serve_process([]) == 1
        assert "schema could not converge" in capsys.readouterr().err
        assert "served" not in record
