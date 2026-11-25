"""Private machine directories do not inherit a permissive process umask."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shlex
import stat
import subprocess

import pytest

from yoke_cli.config import github_git_credential_file, machine_config_file, onboard_apply_report, onboard_checklist, onboard_machine_setup, universe_ui_daemon_state
from yoke_contracts.machine_config import capability_secret_store as capability_secrets
from yoke_contracts.machine_config import secret_files as secrets
from yoke_cli.local_core import state
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.testing.real_home_isolation import set_home
from yoke_contracts.owner_private_path import (
    create_owner_private_directory,
    is_owner_private_directory,
    is_owner_private_file,
    is_others_unwritable_directory,
)

_BUILTIN_USERS = "*S-1-5-32-545"


@contextmanager
def _umask(value: int):
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.mark.parametrize("mask", [0o002, 0o022, 0o077, 0o777])
def test_private_creation_secures_all_new_ancestors(tmp_path: Path, mask: int):
    home = tmp_path / "machine home"
    directory = home / "secrets" / "capabilities" / "project"
    tmp_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    tmp_private = is_owner_private_directory(tmp_path)
    with _umask(mask):
        assert create_private_directory(directory) == directory
        with machine_config_file.exclusive_lock(home / "config.json"):
            pass
    for path in (home, home / "secrets", directory.parent, directory):
        assert is_owner_private_directory(path), path
    # The existing ancestor keeps exactly the access it had before.
    assert stat.S_IMODE(tmp_path.stat().st_mode) == tmp_mode
    assert is_owner_private_directory(tmp_path) == tmp_private
    assert is_owner_private_file(home / "config.json.lock")


@pytest.mark.parametrize(
    "writer",
    [
        "report",
        "checklist",
        "secret",
        "replacement",
        "capability",
        "credential",
        "local-state",
        "local-env",
        "ui-token",
    ],
)
def test_bootstrap_writers_create_private_home_before_config_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
):
    home = tmp_path / "machine home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    with _umask(0o002):
        if writer == "report":
            onboard_apply_report.ApplyReportWriter(
                onboard_apply_report.run_report_path("test"),
                {},
            ).write()
        elif writer == "checklist":
            onboard_checklist._write_json(home / "onboard" / "test.json", {})
        elif writer == "secret":
            secrets.store_machine_secret("test", "token", "test value")
        elif writer == "replacement":
            secrets.replace_secret_file(
                home / "secrets" / "test.token", "test", "value"
            )
        elif writer == "capability":
            capability_secrets.ensure_private_capability_dir(
                home / "secrets" / "capabilities" / "project" / "provider",
            )
        elif writer == "credential":
            github_git_credential_file.write_json_document(
                home / "secrets" / "github" / "credential.json",
                {},
            )
        elif writer == "local-state":
            state.save_state({})
        elif writer == "local-env":
            state.write_env_file({})
        else:
            universe_ui_daemon_state.stable_session_token()
        with machine_config_file.exclusive_lock(home / "config.json"):
            pass
    assert is_owner_private_directory(home)
    for path in home.rglob("*"):
        if path.is_dir():
            assert is_owner_private_directory(path), path


@pytest.mark.posix_only(reason="POSIX permission bits and chmod repair")
def test_existing_writable_home_is_refused_with_exact_repair(tmp_path: Path):
    home = tmp_path / "machine home's directory"
    home.mkdir()
    home.chmod(0o775)
    create_private_directory(home / "onboard" / "reports")
    with pytest.raises(machine_config_file.MachineConfigFileError) as refusal:
        with machine_config_file.exclusive_lock(home / "config.json"):
            pytest.fail("unsafe home accepted")
    assert str(home) in str(refusal.value)
    assert f"chmod 700 {shlex.quote(str(home))}" in str(refusal.value)
    assert stat.S_IMODE(home.stat().st_mode) == 0o775
    assert not (home / "config.json.lock").exists()
    home.chmod(0o700)
    with machine_config_file.exclusive_lock(home / "config.json"):
        pass


@pytest.mark.windows_only(reason="native Windows DACL: icacls loosens and repairs the home")
def test_existing_shared_windows_home_is_refused_with_exact_repair(tmp_path: Path):
    # Mirrors the POSIX 0o775 case: other users may write the config parent.
    # Shared read access alone is allowed (docs/public/cli/machine-config.md).
    home = create_owner_private_directory(tmp_path / "machine home's directory")
    subprocess.run(["icacls", str(home), "/grant", f"{_BUILTIN_USERS}:(M)"], check=True)
    create_private_directory(home / "onboard" / "reports")
    with pytest.raises(machine_config_file.MachineConfigFileError) as refusal:
        with machine_config_file.exclusive_lock(home / "config.json"):
            pytest.fail("unsafe home accepted")
    assert str(home) in str(refusal.value)
    assert "remove other users' write access" in str(refusal.value)
    assert "chmod" not in str(refusal.value)
    assert not is_others_unwritable_directory(home)
    assert not (home / "config.json.lock").exists()
    subprocess.run(["icacls", str(home), "/remove:g", _BUILTIN_USERS], check=True)
    with machine_config_file.exclusive_lock(home / "config.json"):
        pass


def test_existing_file_cannot_be_used_as_directory(tmp_path: Path):
    target = tmp_path / "file"
    target.write_text("unchanged", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_private_directory(target)
    assert target.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.posix_only(reason="POSIX mode bits distinguish shared-read config directories")
def test_setup_preserves_shared_read_on_separate_config_parent(tmp_path, monkeypatch):
    home = create_private_directory(tmp_path / "machine-home")
    parent = home / "selected-config"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    onboard_machine_setup.setup_directories(parent / "config.json")

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert is_owner_private_directory(home)
    assert (parent / "tmp").is_dir() and (parent / "cache").is_dir()
    assert not (parent / "config.json").exists()


@pytest.mark.windows_only(reason="native Windows ACLs distinguish shared-read config and machine home")
def test_setup_accepts_shared_read_config_parent_but_refuses_shared_machine_home(
    tmp_path, monkeypatch
):
    set_home(monkeypatch, str(tmp_path))
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    home = create_private_directory(tmp_path / ".yoke")
    shared = create_private_directory(tmp_path / "shared")
    subprocess.run(
        ["icacls", str(shared), "/grant", f"{_BUILTIN_USERS}:(OI)(CI)(RX)"], check=True
    )
    parent = shared / "selected-config"
    parent.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(parent / "config.json"))
    assert not is_owner_private_directory(parent)
    assert is_others_unwritable_directory(parent)

    onboard_machine_setup.setup_directories(parent / "config.json")

    assert not is_owner_private_directory(parent)
    assert is_owner_private_directory(home)
    assert (parent / "tmp").is_dir() and (parent / "cache").is_dir()
    assert not (parent / "config.json").exists()

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    subprocess.run(["icacls", str(home), "/grant", f"{_BUILTIN_USERS}:(RX)"], check=True)
    with pytest.raises(machine_config_file.MachineConfigFileError, match="not owner-only"):
        onboard_machine_setup.setup_directories(home / "config.json")
    assert not (home / "tmp").exists()
