"""Connection gating, status reads, and registration for ``yoke ui``.

The engine half is stubbed at the dynamic-import seam
(``universe_ui_connection.ui_server``); the server's own behavior is
covered by ``runtime/api/test_universe_ui_server.py``, the daemon's by
``test_yoke_universe_ui_daemon.py``, and the start/stop commands by
``test_yoke_universe_ui_up_down_commands.py``. These tests pin the
allowlist — only non-prod local-postgres serves; https, prod-postgres,
and unrecognized modes refuse in mode language; missing vs malformed
machine config get distinct guidance — plus the fact that bare
``yoke ui`` reads status instead of serving.
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
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


class TestConnectionModeGate:
    def test_no_active_connection_points_to_init(self, machine_home, capsys):
        assert commands.ui_up(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "yoke init --local" in err

    def test_https_connection_refuses_in_mode_language(
        self, machine_home, capsys,
    ):
        from yoke_cli.config import writer

        writer.set_connection(
            "stage", transport="https", api_url="https://api.example",
            token="t" * 40,
        )
        writer.set_active_env("stage")

        assert commands.ui_up(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "hosted/self-host" in err
        assert "machine-local universe" in err

    def test_prod_postgres_connection_stays_operator_only(
        self, machine_home, capsys,
    ):
        write_local_connection("prod-pg", prod=True)

        assert commands.ui_up(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "prod-flagged" in err
        assert "operator-only" in err

    def test_invalid_json_config_names_the_config_problem(
        self, machine_home, capsys,
    ):
        config_file = machine_home / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("{not json", encoding="utf-8")

        assert commands.ui_up(["--no-browser"]) == 1
        err = capsys.readouterr().err
        # An existing-but-broken config is a repair problem, not a
        # missing-universe problem — no init guidance.
        assert str(config_file) in err
        assert "yoke init --local" not in err

    def test_contract_error_on_existing_config_is_not_missing_config(
        self, machine_home, capsys,
    ):
        config_file = machine_home / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({
            "schema_version": 1,
            "active_env": "local",
            "connections": {"local": {"transport": "carrier-pigeon"}},
        }), encoding="utf-8")

        assert commands.ui_up(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert str(config_file) in err
        assert "transport" in err
        assert "yoke init --local" not in err

    def test_unrecognized_connection_mode_fails_closed(
        self, monkeypatch, machine_home, capsys,
    ):
        # The allowlist admits only non-prod local-postgres; a transport
        # this adapter has never heard of must refuse, not serve.
        monkeypatch.setattr(
            connection.machine_config, "active_connection",
            lambda: {"env": "future", "transport": "quantum-relay"},
        )

        assert commands.ui_up(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "non-prod local-postgres" in err
        assert "quantum-relay" in err

    def test_the_serving_child_re_checks_the_connection(
        self, machine_home, capsys,
    ):
        # A launch agent registered while local can be brought back after
        # the machine switched to a hosted connection; the process that
        # actually opens the universe refuses on its own.
        from yoke_cli.config import writer

        writer.set_connection(
            "stage", transport="https", api_url="https://api.example",
            token="t" * 40,
        )
        writer.set_active_env("stage")

        assert serve.ui_serve_process([]) == 1
        assert "hosted/self-host" in capsys.readouterr().err

    def test_status_and_down_carry_no_connection_gate(
        self, monkeypatch, machine_home, capsys,
    ):
        # Nothing is configured at all; reporting on and stopping a
        # process still answers, because neither opens a universe.
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})
        monkeypatch.setattr(
            commands.daemon, "down",
            lambda: {"running": False, "stopped": False},
        )
        assert commands.ui_status([]) == 0
        assert commands.ui_down([]) == 0
        assert capsys.readouterr().err == ""


class TestStatusSurface:
    def test_bare_ui_reports_status_and_never_serves(
        self, monkeypatch, machine_home, capsys,
    ):
        served: dict = {}
        monkeypatch.setattr(connection, "ui_server", lambda: stub_server(served))
        monkeypatch.setattr(commands.daemon, "status", lambda: {"running": False})

        assert commands.ui([]) == 0
        out = capsys.readouterr().out
        assert "yoke ui: stopped" in out
        assert "yoke ui up" in out
        assert served == {}

    def test_status_json_reports_the_door_when_running(
        self, monkeypatch, machine_home, capsys,
    ):
        monkeypatch.setattr(commands.daemon, "status", running_report)

        assert commands.ui_status(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["running"] is True
        assert report["private_url"] == "http://127.0.0.1:9999/?token=stub-token"

    def test_human_status_prints_the_door(
        self, monkeypatch, machine_home, capsys,
    ):
        monkeypatch.setattr(commands.daemon, "status", running_report)

        assert commands.ui([]) == 0
        out = capsys.readouterr().out
        assert "http://127.0.0.1:9999/?token=stub-token" in out
        assert "treat it like a password" in out
        assert "yoke ui down" in out


class TestRegistration:
    @pytest.mark.parametrize("tokens,adapter", [
        (["ui"], "ui"),
        (["ui", "up"], "ui_up"),
        (["ui", "down"], "ui_down"),
        (["ui", "status"], "ui_status"),
        (["ui", "serve-process"], "ui_serve_process"),
    ])
    def test_tool_shaped_resolution_covers_every_ui_verb(self, tokens, adapter):
        resolved = resolve_tool_shaped([*tokens, "--json"])
        assert resolved is not None
        assert resolved[0] is getattr(commands, adapter)
        assert resolved[1] == ["--json"]

    def test_operation_inventory_rows(self):
        from yoke_cli import operation_inventory as inv

        for command in (
            "yoke ui", "yoke ui up", "yoke ui down",
            "yoke ui status", "yoke ui serve-process",
        ):
            row = inv.lookup(command)
            assert row is not None, command
            assert row.status == inv.PERMANENT
            assert row.reason == inv.REASON_TOOL_SHAPED

        org_row = inv.lookup("yoke organizations get")
        assert org_row is not None
        assert org_row.status == inv.WRAPPED

    def test_organizations_get_registered_with_grammar_id(self):
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        function_id, _adapter = SUBCOMMAND_REGISTRY[("organizations", "get")]
        assert function_id == "organizations.get"
