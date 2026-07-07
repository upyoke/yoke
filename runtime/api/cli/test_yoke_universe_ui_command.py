"""Tests for the tool-shaped ``yoke ui`` door.

The engine half is stubbed at the dynamic-import seam
(``universe_ui._ui_server``); the server's own behavior is covered by
``runtime/api/test_universe_ui_server.py``. These tests pin the client
half: connection-mode gating (an allowlist — only non-prod local-postgres
serves; https, prod-postgres, and unrecognized modes refuse in mode
language; missing vs malformed machine config get distinct guidance),
JSON/human output including the ``private_url`` field, and tool-shaped
command resolution.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands import universe_ui as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _stub_server(record: dict, *, busy_port: bool = False):
    def resolve_ui_port(requested=None):
        if busy_port:
            raise RuntimeError(
                "port 9999 is already in use; pick another with --port"
            )
        return int(requested or 9999)

    def serve_ui(*, port, token, open_browser):
        record["served"] = {
            "port": port, "token": token, "open_browser": open_browser,
        }

    return SimpleNamespace(
        resolve_ui_port=resolve_ui_port,
        mint_session_token=lambda: "stub-token",
        private_url=lambda port, token: f"http://127.0.0.1:{port}/?token={token}",
        serve_ui=serve_ui,
    )


def _write_local_connection(env: str = "local", *, prod: bool = False) -> None:
    from yoke_cli.config import writer

    writer.set_connection(
        env, transport="local-postgres",
        dsn="host=/sock user=yoke dbname=yoke", prod=prod,
    )
    writer.set_active_env(env)


class TestConnectionModeGate:
    def test_no_active_connection_points_to_init(self, machine_home, capsys):
        assert commands.ui(["--no-browser"]) == 1
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

        assert commands.ui(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "hosted/self-host" in err
        assert "machine-local universe" in err

    def test_prod_postgres_connection_stays_operator_only(
        self, machine_home, capsys,
    ):
        _write_local_connection("prod-pg", prod=True)

        assert commands.ui(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "prod-flagged" in err
        assert "operator-only" in err

    def test_invalid_json_config_names_the_config_problem(
        self, machine_home, capsys,
    ):
        config_file = machine_home / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("{not json", encoding="utf-8")

        assert commands.ui(["--no-browser"]) == 1
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

        assert commands.ui(["--no-browser"]) == 1
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
            commands.machine_config, "active_connection",
            lambda: {"env": "future", "transport": "quantum-relay"},
        )

        assert commands.ui(["--no-browser"]) == 1
        err = capsys.readouterr().err
        assert "non-prod local-postgres" in err
        assert "quantum-relay" in err


class TestLocalServe:
    def test_json_reports_private_url_and_serves(
        self, monkeypatch, machine_home, capsys,
    ):
        _write_local_connection()
        record: dict = {}
        monkeypatch.setattr(
            commands, "_ui_server", lambda: _stub_server(record),
        )

        assert commands.ui(["--no-browser", "--json"]) == 0

        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["port"] == 9999
        assert report["private_url"] == "http://127.0.0.1:9999/?token=stub-token"
        assert report["browser_opened"] is False
        assert record["served"] == {
            "port": 9999, "token": "stub-token", "open_browser": False,
        }

    def test_human_output_prints_the_door(
        self, monkeypatch, machine_home, capsys,
    ):
        _write_local_connection()
        record: dict = {}
        monkeypatch.setattr(
            commands, "_ui_server", lambda: _stub_server(record),
        )

        assert commands.ui(["--no-browser"]) == 0
        out = capsys.readouterr().out
        assert "http://127.0.0.1:9999/?token=stub-token" in out
        assert "treat it like a password" in out

    def test_explicit_port_passes_through(
        self, monkeypatch, machine_home, capsys,
    ):
        _write_local_connection()
        record: dict = {}
        monkeypatch.setattr(
            commands, "_ui_server", lambda: _stub_server(record),
        )

        assert commands.ui(["--port", "8123", "--no-browser", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["port"] == 8123
        assert record["served"]["port"] == 8123

    def test_busy_port_refusal_names_the_flag(
        self, monkeypatch, machine_home, capsys,
    ):
        _write_local_connection()
        monkeypatch.setattr(
            commands, "_ui_server", lambda: _stub_server({}, busy_port=True),
        )

        assert commands.ui(["--no-browser"]) == 1
        assert "--port" in capsys.readouterr().err


class TestRegistration:
    def test_tool_shaped_resolution_covers_ui(self):
        resolved = resolve_tool_shaped(["ui", "--no-browser"])
        assert resolved is not None
        adapter, remaining = resolved
        assert adapter is commands.ui
        assert remaining == ["--no-browser"]

    def test_operation_inventory_rows(self):
        from yoke_cli import operation_inventory as inv

        ui_row = inv.lookup("yoke ui")
        assert ui_row is not None
        assert ui_row.status == inv.PERMANENT
        assert ui_row.reason == inv.REASON_TOOL_SHAPED

        org_row = inv.lookup("yoke organizations get")
        assert org_row is not None
        assert org_row.status == inv.WRAPPED

    def test_organizations_get_registered_with_grammar_id(self):
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        function_id, _adapter = SUBCOMMAND_REGISTRY[("organizations", "get")]
        assert function_id == "organizations.get"
