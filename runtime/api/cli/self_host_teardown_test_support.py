"""Shared fixtures for ``yoke self-host teardown`` tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.config import machine_uninstall, machine_uninstall_steps, server_connect, writer
from yoke_cli.self_host import first_boot_token, teardown


@pytest.fixture()
def target(tmp_path, installed_self_host_prerequisites) -> Path:
    directory = tmp_path / "yoke-server"
    assert commands.self_host_init(["--admin-name=Ada", f"--dir={directory}"]) == 0
    first_boot_token.token_drop_path(directory).write_text("delivered credential\n")
    return directory


@pytest.fixture()
def docker(monkeypatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def run(argv, **kwargs):
        calls.append(tuple(argv))
        stdout = ""
        if tuple(argv[1:]) == ("compose", "config", "--images"):
            stdout = "ghcr.io/upyoke/yoke-server:latest\npostgres:17\n"
        return subprocess.CompletedProcess(tuple(argv), 0, stdout, "")

    monkeypatch.setattr(teardown, "_WHICH", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(teardown, "_RUN", run)
    return calls


@pytest.fixture()
def machine_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return home


@pytest.fixture()
def identity_probe(monkeypatch) -> dict:
    """Stub the bundle identity probe; tokens in ``accepted`` prove identity."""
    probe: dict = {"accepted": set(), "calls": []}

    def verify(api_url, *, token, timeout_s=None):
        probe["calls"].append((api_url, token))
        if token in probe["accepted"]:
            return {"actor_id": 1}
        raise server_connect.ServerIdentityError(
            f"token verification failed ({api_url}/v1/auth/identity): HTTP 401"
        )

    monkeypatch.setattr(server_connect, "verify_server_identity", verify)
    return probe


def seed_connection(
    tmp_path: Path, *, env: str, api_url: str, token: str = "tok"
) -> None:
    token_file = tmp_path / f"{env}.token"
    token_file.write_text(f"{token}\n", encoding="utf-8")
    writer.set_connection(
        env,
        transport="https",
        api_url=api_url,
        token_file=str(token_file),
    )


def payload(machine_home: Path) -> dict:
    return json.loads((machine_home / "config.json").read_text(encoding="utf-8"))


@pytest.fixture()
def installation_commands(monkeypatch) -> list[tuple]:
    """Stub the local removal commands, keeping config retirement real."""
    calls: list[tuple] = []

    def command(args, *, config):
        calls.append(("yoke", *args))
        assert config.is_file()
        return ""

    def finish(*, config, keep_bundle, emit):
        calls.append(("uninstall", config, keep_bundle))
        emit("CLI: handed off")
        return 0

    monkeypatch.setattr(machine_uninstall_steps, "command", command)
    monkeypatch.setattr(machine_uninstall, "after_self_host_teardown", finish)
    return calls
