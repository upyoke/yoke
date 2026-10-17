"""Credential mutation and binding config-lock failures remain typed."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from yoke_cli.config import github_binding_auth, machine_config, machine_config_file, writer
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_git_credential_store as credential_store
from yoke_cli.config import github_machine_operation

from .github_user_token_test_support import NOW, configured_credential


def test_unsafe_operation_lock_parent_names_the_path(tmp_path, monkeypatch):
    parent = tmp_path / "secrets"
    parent.mkdir(mode=0o775)
    parent.chmod(0o775)
    monkeypatch.setattr(
        github_machine_operation, "operation_lock_target", lambda: parent / ".operation"
    )
    with pytest.raises(credential_store.GitHubCredentialStoreError) as caught:
        with credential_store.machine_operation_lock(tmp_path / "config.json"):
            pytest.fail("an unsafe lock parent must refuse")
    assert f"directory permissions are unsafe: {parent}" in str(caught.value)
    assert parent.stat().st_mode & 0o777 == 0o775


def test_refresh_lock_wraps_parent_creation_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    original_mkdir = credential_file.Path.mkdir

    def fail_secrets_parent(path, *args, **kwargs):
        if path.name == "secrets":
            raise OSError("raw mkdir detail")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(credential_file.Path, "mkdir", fail_secrets_parent)
    with pytest.raises(credential_store.GitHubCredentialStoreError) as caught:
        with credential_store.machine_operation_lock(tmp_path / "config.json"):
            pytest.fail("a failed lock open must refuse")
    assert "operation lock is unavailable" in str(caught.value)
    assert "raw mkdir detail" not in str(caught.value)


def test_github_config_writer_wraps_operation_lock_open_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))

    def fail_open(*args, **kwargs):
        raise OSError("raw open detail")

    monkeypatch.setattr(credential_file.os, "open", fail_open)
    with pytest.raises(writer.MachineConfigWriteError) as caught:
        writer.clear_github(path=tmp_path / "config.json")
    assert "operation lock is unavailable" in str(caught.value)
    assert "raw open detail" not in str(caught.value)


def test_binding_wraps_config_lock_flock_failure(tmp_path, monkeypatch):
    profile = SimpleNamespace(
        api_url="https://api.github.com",
        web_url="https://github.com",
        app_id=123,
        app_slug="example",
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda *_: {"client_id": "example"},
    )
    monkeypatch.setattr(
        github_binding_auth.github_app_public_profile,
        "resolve_selected_and_match",
        lambda *a, **k: profile,
    )
    monkeypatch.setattr(
        github_binding_auth.github_user_tokens,
        "access_token_from_machine_config",
        lambda **k: SimpleNamespace(access_token="stored"),
    )

    def fail_lock(*args, **kwargs):
        raise OSError("raw flock detail")

    monkeypatch.setattr(
        machine_config_file.platform_file_lock,
        "acquire_exclusive",
        fail_lock,
    )
    with pytest.raises(github_binding_auth.GitHubBindingAuthError) as caught:
        github_binding_auth.profile_bound_access_for_binding(tmp_path / "config.json")
    assert "machine-config lock failed" in str(caught.value)
    assert "raw flock detail" not in str(caught.value)


def test_git_helper_turns_refresh_lock_fchmod_failure_into_safe_exit(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config, _ = configured_credential(tmp_path, expires_at=NOW, access_token=None)
    monkeypatch.setattr(
        credential_store.credential_document.clock_contract, "utc_now", lambda: NOW
    )

    def fail_chmod(*args, **kwargs):
        raise OSError("raw chmod detail")

    monkeypatch.setattr(credential_file.os, "fchmod", fail_chmod)
    result = github_git_credential_helper.main(
        ["--config", str(config), "get"],
        stdin=io.StringIO("protocol=https\nhost=github.com\n\n"),
        stdout=io.StringIO(),
    )
    assert result == 1
    error = capsys.readouterr().err
    assert "credential unavailable" in error
    assert "raw chmod detail" not in error
