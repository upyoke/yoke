"""Setup reconnects a registered machine with the server's first-boot admin token."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import (
    machine_registration,
    onboard,
    onboard_preflight,
    onboard_self_host_server as server,
    onboard_session_relay,
    onboard_wizard_self_host as wizard_self_host,
    path_doctor,
    server_connect,
    writer,
    yoke_token_verify,
)
from yoke_cli.self_host import first_boot_token, runtime
from yoke_contracts.machine_config import secret_files as machine_secrets
from yoke_contracts.onboard_destinations import DESTINATION_SERVER
from yoke_contracts.self_host_bootstrap_output import TOKEN_BODY_LENGTH, TOKEN_PREFIX
from yoke_contracts.testing.real_home_isolation import set_home

ENV = "self-host"
URL = "http://127.0.0.1:8765"
SAVED_BEARER = "saved-machine-bearer"
ADMIN_TOKEN = TOKEN_PREFIX + ("B" * TOKEN_BODY_LENGTH)
MINTED_BEARER = "newly-minted-machine-bearer"


@pytest.fixture(autouse=True)
def _machine(tmp_path: Path, monkeypatch) -> Path:
    set_home(monkeypatch, str(tmp_path / "shell-home"))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(path_doctor, "update_shell", lambda: "already configured")
    monkeypatch.setattr(
        path_doctor,
        "verify_fresh_login",
        lambda *_args, **_kwargs: [path_doctor.ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    monkeypatch.setattr(
        onboard_session_relay,
        "install",
        lambda **_kwargs: onboard_session_relay.RelayInstallOutcome(
            installed=True, reused=False
        ),
    )
    config = tmp_path / "home" / "config.json"
    writer.set_connection(
        ENV,
        transport="https",
        api_url=URL,
        token=SAVED_BEARER,
        activate=True,
        path=config,
    )
    return config


def _saved_token() -> str:
    path = machine_secrets.secret_path_no_create(ENV, "token")
    return path.read_text(encoding="utf-8").strip()


def _accept_identity(monkeypatch) -> list[str]:
    seen: list[str] = []

    def verify(_api_url: str, token: str) -> dict:
        seen.append(token)
        return {"ok": True, "actor": {"id": 1}}

    monkeypatch.setattr(yoke_token_verify, "verify", verify)
    return seen


def _registration_mints_bearer(monkeypatch) -> None:
    monkeypatch.setattr(
        machine_registration,
        "_call_register",
        lambda _payload, **_route: SimpleNamespace(
            success=True,
            result={
                "machine": {"machine_id": "machine-1"},
                "credential": {"token": MINTED_BEARER},
            },
        ),
    )


def _setup_with_admin_token(tmp_path: Path, config: Path) -> int:
    token_file = tmp_path / "first-boot-admin-token"
    token_file.write_text(f"{ADMIN_TOKEN}\n", encoding="utf-8")
    return yoke_operations_cli.main(
        [
            "setup",
            "--non-interactive",
            "--config",
            str(config),
            "--env",
            ENV,
            "--api-url",
            URL,
            "--token-file",
            str(token_file),
            "--yes",
            "--json",
        ]
    )


def test_flag_reconnect_replaces_the_saved_bearer(
    tmp_path: Path, monkeypatch, capsys, _machine: Path
) -> None:
    seen = _accept_identity(monkeypatch)
    _registration_mints_bearer(monkeypatch)

    rc = _setup_with_admin_token(tmp_path, _machine)

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "will not overwrite" not in captured.out + captured.err
    assert seen == [ADMIN_TOKEN]
    assert _saved_token() == MINTED_BEARER


def test_rejected_token_fails_on_identity_and_keeps_the_saved_bearer(
    tmp_path: Path, monkeypatch, capsys, _machine: Path
) -> None:
    def reject(_api_url: str, _token: str) -> dict:
        raise yoke_token_verify.YokeTokenVerificationError("token was rejected")

    monkeypatch.setattr(yoke_token_verify, "verify", reject)
    _registration_mints_bearer(monkeypatch)

    rc = _setup_with_admin_token(tmp_path, _machine)

    captured = capsys.readouterr()
    assert rc != 0
    assert "token was rejected" in captured.out + captured.err
    assert _saved_token() == SAVED_BEARER


def test_failed_registration_is_visible_in_the_report(
    tmp_path: Path, monkeypatch, capsys, _machine: Path
) -> None:
    _accept_identity(monkeypatch)
    monkeypatch.setattr(
        machine_registration,
        "_call_register",
        lambda _payload, **_route: SimpleNamespace(
            success=False,
            error={"code": "machine_refused", "message": "registration refused"},
            result=None,
        ),
    )

    rc = _setup_with_admin_token(tmp_path, _machine)

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    report = json.loads(captured.out)
    assert report["machine_registry"]["registered"] is False
    assert "registration refused" in report["machine_registry"]["reason"]


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_wizard_host_here_on_existing_bundle_reconnects(
    tmp_path: Path, monkeypatch, _machine: Path
) -> None:
    bundle_dir = tmp_path / "bundle"
    token_path = first_boot_token.token_drop_path(bundle_dir)
    token_path.parent.mkdir(parents=True)
    token_path.write_text(f"{ADMIN_TOKEN}\n", encoding="utf-8")
    monkeypatch.setattr(server, "_ensure_wizard_bundle", lambda _setup: None)
    monkeypatch.setattr(runtime, "start_bundle", lambda **_kwargs: None)
    monkeypatch.setattr(
        server, "_wait_for_server_health", lambda _setup, **_kwargs: None
    )
    monkeypatch.setattr(server_connect, "_verify_health", lambda *_a, **_k: {})
    monkeypatch.setattr(
        server_connect,
        "verify_server_identity",
        lambda *_a, **_k: {"actor": {"id": 1}},
    )
    monkeypatch.setattr(
        server_connect, "server_identity_summary", lambda identity: identity
    )
    _accept_identity(monkeypatch)
    _registration_mints_bearer(monkeypatch)
    setup = server.SelfHostSetup(
        directory=bundle_dir,
        config_path=str(_machine),
        env_name=ENV,
        port=8765,
        bundle_created=True,
    )

    server.provision(setup, SimpleNamespace(executable="/usr/bin/docker"))
    shell = SimpleNamespace(result=SimpleNamespace(project_mode=None))
    wizard_self_host.select_connection(shell, setup)

    assert shell.result.destination == DESTINATION_SERVER
    assert onboard_preflight.preflight(shell.result).problems == []
    report = onboard.build_report(
        config_path=_machine,
        env_name=shell.result.env_name,
        api_url=shell.result.api_url,
        destination=shell.result.destination,
        token=shell.result.token,
        token_file=shell.result.token_file,
        token_source_kind=shell.result.token_source_kind,
        mode="quick",
        apply=True,
        check_identity=True,
        same_host_self_host=True,
        self_host_directory=str(bundle_dir),
    )

    assert report["applied"] is True
    assert report["machine_registry"]["registered"] is True
    assert _saved_token() == MINTED_BEARER
