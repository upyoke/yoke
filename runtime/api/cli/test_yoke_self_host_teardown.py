"""``yoke self-host teardown`` — what it removes, and what it refuses to."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.commands import self_host_teardown as teardown_commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import writer
from yoke_cli.self_host import bundle, first_boot_token, teardown


@pytest.fixture()
def target(tmp_path) -> Path:
    directory = tmp_path / "yoke-server"
    assert commands.self_host_init(["--dir", str(directory)]) == 0
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


def _seed_connection(tmp_path: Path, *, env: str, api_url: str) -> None:
    token = tmp_path / f"{env}.token"
    token.write_text("tok\n", encoding="utf-8")
    writer.set_connection(
        env, transport="https", api_url=api_url, token_file=str(token),
    )


def _payload(machine_home: Path) -> dict:
    return json.loads((machine_home / "config.json").read_text(encoding="utf-8"))


def test_teardown_is_registered_as_a_tool_shaped_command() -> None:
    resolved, _extra = resolve_tool_shaped(("self-host", "teardown"))
    assert resolved is teardown_commands.self_host_teardown


def test_default_teardown_stops_the_stack_and_keeps_the_data(target, docker):
    report = teardown.tear_down(directory=str(target), keep_connection=True)

    assert docker == [("/usr/bin/docker", "compose", "down")]
    assert report["universe_destroyed"] is False
    # The bundle survives, so `docker compose up -d` brings it all back.
    assert (target / bundle.COMPOSE_FILE_NAME).is_file()
    assert first_boot_token.token_drop_path(target).is_file()


def test_destroying_the_universe_takes_its_own_flag(target, docker):
    report = teardown.tear_down(
        directory=str(target), destroy_universe=True, keep_connection=True,
    )

    assert docker == [("/usr/bin/docker", "compose", "down", "-v")]
    assert report["universe_destroyed"] is True


def test_destroy_universe_refuses_without_consent_when_not_a_tty(
    target, docker, monkeypatch, capsys,
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    rc = teardown_commands.self_host_teardown([
        "--dir", str(target), "--destroy-universe", "--keep-connection",
    ])

    assert rc == 1
    assert "pass --yes to consent" in capsys.readouterr().err
    # The refusal came before docker was asked to do anything.
    assert docker == []


def test_images_are_read_before_the_stack_goes_down(target, docker):
    report = teardown.tear_down(
        directory=str(target), remove_images=True, keep_connection=True,
    )

    assert docker[0] == ("/usr/bin/docker", "compose", "config", "--images")
    assert docker[1] == ("/usr/bin/docker", "compose", "down")
    assert report["images_removed"] == [
        "ghcr.io/upyoke/yoke-server:latest",
        "postgres:17",
    ]
    assert ("/usr/bin/docker", "image", "rm", "postgres:17") in docker


def test_an_image_still_in_use_is_reported_not_forced(target, monkeypatch):
    def run(argv, **kwargs):
        stdout = ""
        code = 0
        if tuple(argv[1:]) == ("compose", "config", "--images"):
            stdout = "postgres:17\n"
        if tuple(argv[1:3]) == ("image", "rm"):
            code = 1
        return subprocess.CompletedProcess(tuple(argv), code, stdout, "in use")

    monkeypatch.setattr(teardown, "_WHICH", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(teardown, "_RUN", run)

    report = teardown.tear_down(
        directory=str(target), remove_images=True, keep_connection=True,
    )

    assert report["images_removed"] == []
    assert report["images_retained"] == ["postgres:17"]


def test_remove_bundle_deletes_yoke_files_and_keeps_operator_files(target, docker):
    (target / "notes.txt").write_text("mine\n", encoding="utf-8")

    report = teardown.tear_down(
        directory=str(target), remove_bundle=True, keep_connection=True,
    )

    token_file = first_boot_token.token_drop_path(target)
    assert not token_file.exists()
    assert not (target / bundle.SECRETS_DIR_NAME).exists()
    assert not (target / bundle.COMPOSE_FILE_NAME).exists()
    assert (target / "notes.txt").is_file()
    assert str(target / "notes.txt") in report["bundle_files_retained"]
    assert str(token_file) in report["bundle_files_removed"]


def test_remove_bundle_removes_an_emptied_directory(target, docker):
    teardown.tear_down(
        directory=str(target), remove_bundle=True, keep_connection=True,
    )

    assert not target.exists()


def test_teardown_retires_the_connection_pointing_at_this_bundle(
    target, docker, tmp_path, machine_home,
):
    _seed_connection(tmp_path, env="self-host", api_url="http://127.0.0.1:8765")
    config = machine_home / "config.json"

    report = teardown.tear_down(directory=str(target), config_path=str(config))

    assert report["connection"]["removed_env"] == "self-host"
    payload = _payload(machine_home)
    assert payload["connections"] == {}
    # The machine is now honestly unconfigured rather than pointed at a
    # server that no longer answers — and no file was hand-edited to get here.
    assert payload.get("active_env", "") == ""


def test_a_connection_for_another_server_is_left_alone(
    target, docker, tmp_path, machine_home,
):
    _seed_connection(tmp_path, env="hosted", api_url="https://yoke.internal")

    report = teardown.tear_down(
        directory=str(target), config_path=str(machine_home / "config.json"),
    )

    assert report["connection"] is None
    assert list(_payload(machine_home)["connections"]) == ["hosted"]


def test_retiring_the_active_authority_with_peers_names_the_choice(
    tmp_path, machine_home,
):
    _seed_connection(tmp_path, env="self-host", api_url="http://127.0.0.1:8765")
    _seed_connection(tmp_path, env="hosted", api_url="https://app.upyoke.com/api")

    with pytest.raises(writer.MachineConfigWriteError) as raised:
        writer.remove_connection("self-host")

    assert "--activate ENV" in str(raised.value)
    assert "'hosted'" in str(raised.value)

    result = writer.remove_connection("self-host", activate="hosted")

    assert result["active_env"] == "hosted"
    assert list(_payload(machine_home)["connections"]) == ["hosted"]


def test_teardown_refuses_a_directory_that_is_not_a_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(teardown, "_WHICH", lambda _name: "/usr/bin/docker")

    with pytest.raises(teardown.SelfHostTeardownError) as raised:
        teardown.tear_down(directory=str(tmp_path))

    assert "--dir PATH" in str(raised.value)


def test_a_failed_compose_down_removes_nothing_else(target, monkeypatch):
    monkeypatch.setattr(teardown, "_WHICH", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        teardown,
        "_RUN",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            tuple(argv), 1, "", "daemon not running",
        ),
    )

    with pytest.raises(teardown.SelfHostTeardownError) as raised:
        teardown.tear_down(directory=str(target), remove_bundle=True)

    assert "daemon not running" in str(raised.value)
    assert stat.S_ISREG(
        first_boot_token.token_drop_path(target).stat().st_mode
    )
