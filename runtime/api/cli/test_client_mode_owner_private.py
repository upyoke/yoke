"""Client-mode tokens and machine config stay owner-only on every OS.

Windows facts are faked at the shared ``owner_private_path`` checks and each
module's ``_WINDOWS`` flag, so the Windows branches run on every runner.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_cli.config import (
    github_git_credential_file,
    github_git_credential_permissions,
    machine_config_file,
    status_environment,
    writer_connection_remove,
)
from yoke_cli.config.machine_config_mutation import MachineConfigWriteError
from yoke_contracts import owner_private_path

pytestmark = pytest.mark.windows

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")


class _Refused(RuntimeError):
    pass


def _fake_acl(monkeypatch, *, files: bool = True, directories: bool = True) -> None:
    monkeypatch.setattr(owner_private_path, "is_owner_private_file", lambda _p: files)
    monkeypatch.setattr(
        owner_private_path, "is_owner_private_directory", lambda _p: directories
    )


def _as_windows(monkeypatch, *modules) -> None:
    for module in modules:
        monkeypatch.setattr(module, "_WINDOWS", True)
    monkeypatch.setattr(
        os, "fchmod", _raise("Windows has no fchmod before Python 3.13"), raising=False
    )


def _raise(message: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(message)

    return fail


# --- GitHub credential helper permissions ---------------------------------


@pytest.mark.parametrize("private", [True, False])
def test_credential_directory_follows_the_shared_acl_check(
    monkeypatch, tmp_path: Path, private: bool
) -> None:
    _fake_acl(monkeypatch, directories=private)
    check = lambda: github_git_credential_permissions.assert_secure_parent(  # noqa: E731
        tmp_path, _Refused
    )
    if private:
        check()
        return
    with pytest.raises(_Refused, match="is not owner-only.*chmod 700"):
        check()


def test_windows_credential_directory_refusal_names_the_acl_repair(
    monkeypatch, tmp_path: Path
) -> None:
    _fake_acl(monkeypatch, directories=False)
    _as_windows(monkeypatch, github_git_credential_permissions)
    # Windows has no "others may read" middle ground: both modes need the DACL.
    with pytest.raises(_Refused, match="only your Windows account, SYSTEM"):
        github_git_credential_permissions.assert_secure_parent(
            tmp_path, _Refused, require_private=False
        )


@pytest.mark.parametrize("private", [True, False])
def test_credential_file_follows_the_shared_acl_check(
    monkeypatch, tmp_path: Path, private: bool
) -> None:
    path = tmp_path / "token.json"
    path.write_text("{}", encoding="utf-8")
    _fake_acl(monkeypatch, files=private)
    _as_windows(monkeypatch, github_git_credential_permissions)
    check = lambda: github_git_credential_permissions.assert_owner_only_file(  # noqa: E731
        path.stat(), path, _Refused
    )
    if private:
        check()
        return
    with pytest.raises(_Refused, match="not owner-only.*Windows account"):
        check()


def test_windows_credential_write_and_lock_use_no_posix_modes(
    monkeypatch, tmp_path: Path
) -> None:
    written: list[tuple[Path, bytes]] = []
    _fake_acl(monkeypatch)
    _as_windows(monkeypatch, github_git_credential_file, github_git_credential_permissions)
    monkeypatch.setattr(
        owner_private_path,
        "write_owner_private",
        lambda path, data: written.append((Path(path), data)),
    )
    target = tmp_path / "secrets" / "github.json"

    github_git_credential_file.write_json_document(target, {"token": "t"})
    with github_git_credential_file.exclusive_lock(target):
        pass

    assert written == [(target, b'{"token": "t"}\n')]


def test_credential_write_failure_is_named(monkeypatch, tmp_path: Path) -> None:
    def deny(_path, _data):
        raise OSError("owner_private_write_failed: disk full")

    monkeypatch.setattr(owner_private_path, "write_owner_private", deny)
    with pytest.raises(
        github_git_credential_file.CredentialFileError,
        match="could not be written.*reconnect GitHub",
    ):
        github_git_credential_file.write_json_document(tmp_path / "g.json", {})


# --- Machine config file --------------------------------------------------


@POSIX_ONLY
def test_machine_config_write_is_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    machine_config_file.atomic_write_text(target, "{}\n")
    assert target.read_text(encoding="utf-8") == "{}\n"
    assert owner_private_path.is_owner_private_file(target)


def test_machine_config_write_failure_is_named(monkeypatch, tmp_path: Path) -> None:
    def deny(_path, _data):
        raise OSError("owner_private_write_failed")

    monkeypatch.setattr(owner_private_path, "write_owner_private", deny)
    with pytest.raises(machine_config_file.MachineConfigFileError, match="check free"):
        machine_config_file.atomic_write_text(tmp_path / "config.json", "{}")


@POSIX_ONLY
def test_machine_state_directory_left_at_umask_is_tightened(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    home.chmod(0o755)
    machine_config_file.ensure_owner_only_directory(home)
    assert owner_private_path.is_owner_private_directory(home)


def test_windows_machine_state_directory_is_refused_not_repaired(
    monkeypatch, tmp_path: Path
) -> None:
    _fake_acl(monkeypatch, directories=False)
    _as_windows(monkeypatch, machine_config_file)
    monkeypatch.setattr(Path, "chmod", _raise("Windows ACLs are never chmodded"))
    with pytest.raises(machine_config_file.MachineConfigFileError, match="SYSTEM"):
        machine_config_file.ensure_owner_only_directory(tmp_path)


@pytest.mark.parametrize("private", [True, False])
def test_windows_machine_config_lock_follows_the_shared_acl_check(
    monkeypatch, tmp_path: Path, private: bool
) -> None:
    _fake_acl(monkeypatch, files=private)
    _as_windows(monkeypatch, machine_config_file)
    lock = lambda: machine_config_file.exclusive_lock(tmp_path / "config.json")  # noqa: E731
    if private:
        with lock():
            pass
        return
    with pytest.raises(
        machine_config_file.MachineConfigFileError, match="lock is not owner-only"
    ):
        with lock():
            pass


def test_windows_idle_lock_is_closed_before_unlink(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.json"
    _fake_acl(monkeypatch)
    with machine_config_file.exclusive_lock(config):
        pass
    _as_windows(monkeypatch, machine_config_file)
    lock = machine_config_file.config_lock_path(config)

    assert machine_config_file.remove_idle_lock_file(lock) is True
    assert not lock.exists()


def test_windows_lock_opened_by_another_process_is_reported_busy(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.json"
    _fake_acl(monkeypatch)
    with machine_config_file.exclusive_lock(config):
        pass
    _as_windows(monkeypatch, machine_config_file)

    def sharing_violation(self, *args, **kwargs):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(Path, "unlink", sharing_violation)
    with pytest.raises(machine_config_file.MachineConfigFileError, match="busy"):
        machine_config_file.remove_idle_lock_file(
            machine_config_file.config_lock_path(config)
        )


# --- Connection removal and status ----------------------------------------


@pytest.mark.parametrize("private", [True, False])
def test_connection_credential_removal_follows_the_shared_acl_check(
    monkeypatch, tmp_path: Path, private: bool
) -> None:
    secret = tmp_path / "connection.token"
    secret.write_text("t", encoding="utf-8")
    _fake_acl(monkeypatch, files=private)
    check = lambda: writer_connection_remove._require_owner_only(  # noqa: E731
        secret, env="prod"
    )
    if private:
        check()
        return
    with pytest.raises(MachineConfigWriteError, match="non-owner credential for 'prod'"):
        check()


@pytest.mark.parametrize("windows", [False, True])
def test_status_reports_a_shared_config_with_its_platform_repair(
    monkeypatch, tmp_path: Path, windows: bool
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    _fake_acl(monkeypatch, files=False)
    monkeypatch.setattr(status_environment, "_WINDOWS", windows)

    (issue,) = status_environment.permission_issues(config)

    assert issue["code"] == "config_permissions"
    assert ("Windows account" in issue["hint"]) is windows
    assert ("chmod 600" in issue["hint"]) is not windows


def test_status_accepts_an_owner_only_config(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    _fake_acl(monkeypatch, files=True)
    assert status_environment.permission_issues(config) == []
