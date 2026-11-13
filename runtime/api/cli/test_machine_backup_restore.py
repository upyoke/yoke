"""Offline backups preserve bytes without leaking credential contents."""

from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import machine_backup as cli
from yoke_cli.config import machine_backup as storage
from yoke_cli.config.machine_backup_files import MachineBackupError
from yoke_contracts.machine_config.capability_secrets import (
    browser_profile_relative_path,
)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home / ".yoke"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    root = home / ".yoke"
    (root / "secrets").mkdir(parents=True)
    (root / "config.json").write_text('{"connections": {}}\n')
    return home, root, tmp_path / "backup"


def test_round_trip_and_incremental_backup(machine):
    home, root, folder = machine
    secret = root / "secrets" / "token"
    secret.write_bytes(b"private-value\x00\xff")
    (root / "ssh").mkdir()
    (root / "ssh" / "identity").write_bytes(b"ssh-key")
    expected = {
        p.relative_to(home): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert storage.backup(folder)["changed"] == 3
    times = {p: p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()}
    assert storage.backup(folder)["changed"] == 0
    assert all(p.stat().st_mtime_ns == timestamp for p, timestamp in times.items())
    for path in expected:
        (home / path).unlink()
    assert storage.restore(folder)["changed"] == 3
    assert {name: (home / name).read_bytes() for name in expected} == expected
    for name in expected:
        assert stat.S_IMODE((home / name).stat().st_mode) == 0o600
        assert stat.S_IMODE((home / name).parent.stat().st_mode) == 0o700
    secret.write_bytes(b"rotated")
    assert storage.backup(folder)["changed"] == 1
    assert (folder / "home/.yoke/secrets/token").read_bytes() == b"rotated"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert all(
        set(entry) == {"name", "mode", "size", "sha256"} for entry in manifest["files"]
    )


@pytest.mark.parametrize(
    "excluded",
    [
        "a.lock",
        "a.stale.old",
        "YOKE_LOCAL_DSN_VALIDATION_123",
        "yoke_validation_abc.dsn",
        "github-app-user-operator.json",
        "installer-live-tui/token",
        str(browser_profile_relative_path("sample") / "Cookies"),
        str(browser_profile_relative_path("sample", "work") / "Cookies"),
    ],
)
def test_skip_list(machine, excluded):
    _, root, folder = machine
    path = root / "secrets" / excluded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("excluded-secret")
    (root / "secrets/keep").write_text("retained")
    storage.backup(folder)
    assert not (folder / "home/.yoke/secrets" / excluded).exists()
    assert (folder / "home/.yoke/secrets/keep").read_text() == "retained"


def test_external_files_and_new_home_paths(machine, tmp_path, monkeypatch):
    home, root, folder = machine
    (home / "credentials").mkdir()
    (home / "credentials/token").write_text("access-token")
    (home / "credentials/key").write_text("ssh-private")
    config = {
        "connections": {
            "remote": {
                "credential_source": {
                    "kind": "token_file",
                    "path": str(home / "credentials/token"),
                },
                "postgres": {
                    "tunnel": {"identity_file": str(home / "credentials/key")}
                },
            },
            "absent": {
                "credential_source": {
                    "kind": "dsn_file",
                    "path": "~/credentials/missing",
                }
            },
        }
    }
    (root / "config.json").write_text(json.dumps(config))
    assert storage.backup(folder)["missing"] == ["credentials/missing"]
    destination = tmp_path / "new-home"
    destination.mkdir()
    monkeypatch.setenv("HOME", str(destination))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(destination / ".yoke"))
    storage.restore(folder)
    restored = json.loads((destination / ".yoke/config.json").read_text())
    assert restored["connections"]["remote"]["credential_source"]["path"] == str(
        destination / "credentials/token"
    )
    assert restored["connections"]["remote"]["postgres"]["tunnel"][
        "identity_file"
    ] == str(destination / "credentials/key")
    assert (destination / "credentials/token").read_text() == "access-token"


@pytest.mark.parametrize("damage", ["mismatch", "missing"])
def test_invalid_backup_writes_nothing(machine, damage):
    _, root, folder = machine
    (root / "secrets/token").write_text("original-secret")
    storage.backup(folder)
    payload = folder / "home/.yoke/secrets/token"
    if damage == "missing":
        payload.unlink()
    else:
        payload.write_text("damaged-secret")
    (root / "config.json").unlink()
    with pytest.raises(MachineBackupError, match="secrets/token") as failure:
        storage.restore(folder)
    assert "secret" not in str(failure.value).replace("secrets/token", "")
    assert not (root / "config.json").exists()


def test_conflicts_preflight_entire_restore(machine):
    _, root, folder = machine
    (root / "secrets/token").write_text("old")
    storage.backup(folder)
    (root / "secrets/token").write_text("new")
    (root / "config.json").unlink()
    with pytest.raises(MachineBackupError, match="--replace"):
        storage.restore(folder)
    assert not (root / "config.json").exists()
    storage.restore(folder, replace=True)
    assert (root / "secrets/token").read_text() == "old"


@pytest.mark.parametrize("unsafe", ["../escape", "/tmp/escape", "a/../escape"])
def test_manifest_traversal_refuses(machine, unsafe):
    _, _, folder = machine
    storage.backup(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["files"][0]["name"] = unsafe
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(MachineBackupError, match="unsafe_name"):
        storage.restore(folder, replace=True)


def test_symlinks_refuse_and_removed_secrets_leave_backup(machine, tmp_path):
    _, root, folder = machine
    token = root / "secrets/token"
    token.write_text("private")
    storage.backup(folder)
    token.unlink()
    storage.backup(folder)
    assert not (folder / "home/.yoke/secrets/token").exists()
    token.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(MachineBackupError, match="symlink"):
        storage.backup(folder)


def test_cli_no_secret_output_and_doctor_failure(machine, monkeypatch, capsys):
    _, root, folder = machine
    (root / "secrets/token").write_text("never-print-this-token")
    assert cli.machine_backup(["--to", str(folder)]) == 0
    calls = []

    def doctor(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=1,
            stdout="never-print-this-token",
            stderr="never-print-this-token",
        )

    monkeypatch.setattr(cli.subprocess, "run", doctor)
    assert cli.machine_restore(["--from", str(folder)]) == 1
    output = capsys.readouterr()
    assert "never-print-this-token" not in output.out + output.err
    assert "doctor_failed" in output.err
    assert "yoke github connect" in output.out
    assert calls[0][0] == ["yoke", "doctor", "run", "--only", "connections"]
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
    )
    assert cli.machine_restore(["--from", str(folder)]) == 0


def test_home_alias_and_blocked_destination_parent(machine, tmp_path, monkeypatch):
    home, root, folder = machine
    alias = tmp_path / "home-alias"
    alias.symlink_to(home, target_is_directory=True)
    monkeypatch.setenv("HOME", str(alias))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(alias / ".yoke"))
    (home / "credentials").mkdir()
    (home / "credentials/token").write_text("private")
    (root / "config.json").write_text(
        json.dumps(
            {
                "connections": {
                    "remote": {
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(alias / "credentials/token"),
                        }
                    }
                }
            }
        )
    )
    storage.backup(folder)
    (home / "credentials/token").unlink()
    (home / "credentials").rmdir()
    (home / "credentials").write_text("parent-file")
    (root / "config.json").unlink()
    with pytest.raises(MachineBackupError, match="parent_not_directory"):
        storage.restore(folder, replace=True)
    assert not (root / "config.json").exists()


def test_registered_without_control_plane():
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    assert (
        resolve_tool_shaped(["machine", "backup", "--to", "folder"])[0]
        is cli.machine_backup
    )
    assert (
        resolve_tool_shaped(["machine", "restore", "--from", "folder"])[0]
        is cli.machine_restore
    )


def test_backup_preserves_unrelated_destination(machine):
    _, _, folder = machine
    unrelated = folder / "home/photo"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"unrelated-data")
    with pytest.raises(MachineBackupError, match="destination_not_backup"):
        storage.backup(folder)
    assert unrelated.read_bytes() == b"unrelated-data"
