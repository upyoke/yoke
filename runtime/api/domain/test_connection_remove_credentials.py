"""Credential ownership and sharing during machine connection retirement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.config import writer
from yoke_cli.config.machine_config_mutation import MachineConfigWriteError


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    token = tmp_path / "input.token"
    token.write_text("test-token\n")
    for env in ("primary", "retiring", "external"):
        writer.set_connection(
            env,
            transport="https",
            api_url="https://api.example",
            token_file=str(token),
        )
    return home


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text())


def _set_credential_path(home: Path, env: str, path: Path) -> dict:
    payload = _config(home)
    payload["connections"][env]["credential_source"]["path"] = str(path)
    (home / "config.json").write_text(json.dumps(payload))
    return payload


@pytest.mark.parametrize("external_exists", [True, False])
def test_removal_ignores_other_alias_external_credential(
    machine_home, tmp_path, external_exists
):
    external = tmp_path / "external.token"
    if external_exists:
        external.write_text("external-token\n")
    before = _set_credential_path(machine_home, "external", external)

    report = writer.remove_connection("retiring")

    assert report["credential_removed"] is True
    assert report["credential_retained_shared"] is False
    assert not (machine_home / "secrets" / "retiring.token").exists()
    expected = before.copy()
    expected["connections"] = {
        alias: entry
        for alias, entry in before["connections"].items()
        if alias != "retiring"
    }
    expected["projects"] = before.get("projects", [])
    assert _config(machine_home) == expected
    assert external.exists() is external_exists
    if external_exists:
        assert external.read_text() == "external-token\n"


def test_removal_refuses_own_external_credential_without_mutating(
    machine_home, tmp_path
):
    external = tmp_path / "external.token"
    external.write_text("external-token\n")
    before = _set_credential_path(machine_home, "retiring", external)

    with pytest.raises(
        MachineConfigWriteError,
        match="refusing to remove a credential outside Yoke-owned machine secrets",
    ):
        writer.remove_connection("retiring")

    assert _config(machine_home) == before
    assert external.read_text() == "external-token\n"
    assert (machine_home / "secrets" / "retiring.token").exists()


@pytest.mark.parametrize("through_symlink", [True, False])
def test_removal_retains_owned_secret_shared_with_remaining_alias(
    machine_home, tmp_path, through_symlink
):
    shared = machine_home / "secrets" / "retiring.token"
    reference = shared
    if through_symlink:
        reference = tmp_path / "shared.token"
        reference.symlink_to(shared)
    _set_credential_path(machine_home, "primary", reference)
    external = tmp_path / "external.token"
    external.write_text("external-token\n")
    before = _set_credential_path(machine_home, "external", external)

    report = writer.remove_connection("retiring")

    assert report["credential_removed"] is False
    assert report["credential_retained_shared"] is True
    assert shared.read_text() == "test-token\n"
    assert _config(machine_home)["connections"] == {
        alias: entry
        for alias, entry in before["connections"].items()
        if alias != "retiring"
    }
    assert _config(machine_home)["active_env"] == "primary"
    assert external.read_text() == "external-token\n"
