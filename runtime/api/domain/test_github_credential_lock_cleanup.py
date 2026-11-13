"""Deleting an owned GitHub credential takes its idle lock file with it."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.github_machine_config_concurrency_test_support import (
    _seed_connection,
)
from yoke_cli.config import github_git_credential_document as document
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_git_credential_store as store
from yoke_cli.config import github_machine_credential_lifecycle as lifecycle
from yoke_cli.config import machine_config_file
from yoke_cli.config import writer_github


@pytest.fixture()
def credential(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    path = home / "secrets" / f"github-app-user-{'a' * 32}.json"
    store.write_credential_document(
        path,
        {
            "schema_version": 2,
            "refresh_token": "refresh-token",
            "refresh_expires_at": "2099-12-09T17:00:00+00:00",
        },
    )
    with credential_file.exclusive_lock(path):
        pass
    assert credential_file.lock_path(path).exists()
    return path


def test_owned_removal_deletes_lock(credential):
    assert lifecycle.remove_owned_credential(credential) is True
    assert not credential.exists()
    assert not credential_file.lock_path(credential).exists()


def test_quarantined_removal_deletes_lock(credential):
    quarantine = lifecycle.quarantine_owned_credential(credential)
    assert quarantine is not None
    assert lifecycle.remove_quarantined_credential(quarantine) is True
    assert not quarantine.exists()
    assert not credential_file.lock_path(quarantine).exists()
    assert document.is_quarantined_credential_name(quarantine.name)


def test_orphan_lock_goes_when_credential_is_already_gone(credential):
    credential.unlink()
    assert lifecycle.remove_owned_credential(credential) is False
    assert not credential_file.lock_path(credential).exists()


def test_released_config_credential_deletes_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    config = tmp_path / "config.json"
    _entry, path = _seed_connection(config, "retiring")
    with credential_file.exclusive_lock(path):
        pass
    report = writer_github._release_owned_credential(str(path), config, delete=True)
    assert report["removed"] is True
    assert not path.exists()
    assert not credential_file.lock_path(path).exists()


def test_busy_lock_never_fails_a_successful_delete(credential, monkeypatch):
    def busy(path):
        raise machine_config_file.MachineConfigFileError(
            f"machine-state lock is busy: {path}"
        )

    monkeypatch.setattr(machine_config_file, "remove_idle_lock_file", busy)
    assert lifecycle.remove_owned_credential(credential) is True
    assert not credential.exists()
    assert credential_file.lock_path(credential).exists()
