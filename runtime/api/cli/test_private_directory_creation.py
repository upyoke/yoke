"""Private machine directories do not inherit a permissive process umask."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shlex
import stat

import pytest

from yoke_cli.config import (
    capability_secrets,
    github_git_credential_file,
    machine_config_file,
    onboard_apply_report,
    onboard_checklist,
    secrets,
    universe_ui_daemon_state,
)
from yoke_cli.local_core import state
from yoke_contracts.machine_config.directories import create_private_directory


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
    with _umask(mask):
        assert create_private_directory(directory) == directory
        with machine_config_file.exclusive_lock(home / "config.json"):
            pass
    for path in (home, home / "secrets", directory.parent, directory):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "config.json.lock").stat().st_mode) == 0o600


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
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    for path in home.rglob("*"):
        if path.is_dir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o700


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


def test_existing_file_cannot_be_used_as_directory(tmp_path: Path):
    target = tmp_path / "file"
    target.write_text("unchanged", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_private_directory(target)
    assert target.read_text(encoding="utf-8") == "unchanged"
