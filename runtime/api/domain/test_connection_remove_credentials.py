"""Credential ownership and sharing during machine connection retirement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.github_machine_config_concurrency_test_support import (
    _seed_connection,
)
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import writer


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
    assert _config(machine_home) == expected
    assert external.exists() is external_exists
    if external_exists:
        assert external.read_text() == "external-token\n"


@pytest.mark.parametrize("external_exists", [True, False])
def test_removal_keeps_own_external_credential_and_reports_it(
    machine_home, tmp_path, external_exists
):
    external = tmp_path / "external.token"
    if external_exists:
        external.write_text("external-token\n")
    before = _set_credential_path(machine_home, "retiring", external)

    report = writer.remove_connection("retiring")

    assert report["credential_removed"] is False
    assert report["credential_retained_foreign"] is True
    assert "retiring" not in _config(machine_home)["connections"]
    assert set(_config(machine_home)["connections"]) == (
        set(before["connections"]) - {"retiring"}
    )
    assert external.exists() is external_exists
    if external_exists:
        assert external.read_text() == "external-token\n"


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


def test_connection_removal_drops_only_its_project_mappings(
    machine_home, tmp_path, monkeypatch
):
    kept, retired = tmp_path / "kept", tmp_path / "retired"
    kept.mkdir()
    retired.mkdir()
    writer.register_project(kept, 7)
    monkeypatch.setenv("YOKE_ENV", "retiring")
    writer.register_project(retired, 8)
    monkeypatch.delenv("YOKE_ENV")
    before = _config(machine_home)["connection_projects"]
    assert set(before) == {"primary", "retiring"}

    report = writer.remove_connection("retiring")

    assert report["project_mappings_removed"] == 1
    assert _config(machine_home)["connection_projects"] == {
        "primary": before["primary"]
    }


def test_connection_removal_releases_its_github_authorization(machine_home):
    config = machine_home / "config.json"
    seeded = {env: _seed_connection(config, env) for env in ("retiring", "primary")}
    refs = {env: path for env, (_entry, path) in seeded.items()}
    payload = _config(machine_home)
    payload["connection_github"] = {
        env: entry for env, (entry, _path) in seeded.items()
    }
    config.write_text(json.dumps(payload))

    report = writer.remove_connection("retiring")

    assert report["github_credential_cleanup"] == {
        "released": True,
        "removed": True,
        "pending": False,
        "shared": False,
    }
    assert _config(machine_home)["connection_github"] == {
        "primary": seeded["primary"][0]
    }
    assert not refs["retiring"].exists()
    assert not credential_file.lock_path(refs["retiring"]).exists()
    assert refs["primary"].is_file()
