"""Engine commands on a machine without `yoke setup` name `yoke setup`, not a DSN."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli import main as cli_main
from yoke_cli.transport import dispatcher
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_contracts.machine_config import setup_status

INSTALLER_CONFIG = {
    "machine_id": "444a6196-0000-4000-8000-000000000000",
    "schema_version": 1,
    "settings": {
        "distribution": {"origin": "https://api.upyoke.com", "channel": "stable"}
    },
}
AUTHORITY_ENVS = (*setup_status.DATABASE_AUTHORITY_ENVS, "YOKE_ENV", "YOKE_MACHINE_CONFIG_FILE")


@pytest.fixture()
def installer_only_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    home.mkdir()
    config = home / "config.json"
    config.write_text(json.dumps(INSTALLER_CONFIG), encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AUTHORITY_ENVS:
        monkeypatch.delenv(name, raising=False)
    return home


def test_helper_refuses_only_without_setup_or_database_authority(
    installer_only_home: Path,
) -> None:
    error = setup_status.not_set_up_error(INSTALLER_CONFIG, {})

    assert error is not None
    assert error.code == "machine_not_set_up"
    assert str(installer_only_home / "config.json") in error.message
    assert error.recovery_hint == "Run `yoke setup`."
    for name in setup_status.DATABASE_AUTHORITY_ENVS:
        assert setup_status.not_set_up_error(INSTALLER_CONFIG, {name: "x"}) is None
    configured = {**INSTALLER_CONFIG, "connections": {"local": {"transport": "postgres"}}}
    assert setup_status.not_set_up_error(configured, {}) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["projects", "list"],
        ["items", "list"],
        ["db", "read", "SELECT 1"],
    ],
)
def test_engine_commands_refuse_with_machine_not_set_up(
    installer_only_home: Path, argv: list[str], capsys
) -> None:
    code = cli_main.main(argv)
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert code != 0
    assert "machine_not_set_up" in output
    assert "Run `yoke setup`" in output
    assert "handler_exception" not in output
    assert "YOKE_PG_DSN" not in output


def _local_ok(request):
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"rows": []},
    )


def _dispatch() -> FunctionCallResponse:
    return dispatcher.call_dispatcher(
        function_id="projects.list",
        target=TargetRef(kind="global"),
        _local_dispatch=_local_ok,
    )


def test_dispatch_refuses_before_engine_when_not_set_up(installer_only_home: Path) -> None:
    response = _dispatch()

    assert response.success is False
    assert response.error.code == "machine_not_set_up"


def test_dispatch_runs_engine_with_dsn_in_environment(
    installer_only_home: Path, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_PG_DSN", "host=/sock dbname=yoke")

    assert _dispatch().success is True


def test_dispatch_runs_engine_with_configured_connection(
    installer_only_home: Path,
) -> None:
    config = installer_only_home / "config.json"
    payload = {
        **INSTALLER_CONFIG,
        "connections": {"local": {"transport": "postgres"}},
        "settings": {**INSTALLER_CONFIG["settings"], "env": "local"},
    }
    config.write_text(json.dumps(payload), encoding="utf-8")

    assert _dispatch().success is True
