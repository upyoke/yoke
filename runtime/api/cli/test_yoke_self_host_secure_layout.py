"""Directory and existing-file authority tests for self-host bundles."""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.self_host import secure_layout


def test_init_refuses_secrets_symlink_before_external_write(tmp_path, capsys):
    target = tmp_path / "bundle"
    target.mkdir()
    external = tmp_path / "external-secrets"
    external.mkdir(mode=0o700)
    sentinel = external / "sentinel"
    sentinel.write_bytes(b"keep\n")
    (target / "secrets").symlink_to(external, target_is_directory=True)

    assert commands.self_host_init(["--dir", str(target)]) == 1
    error = capsys.readouterr().err
    assert "real directory, not a symlink" in error
    assert sentinel.read_bytes() == b"keep\n"
    assert not (target / ".env").exists()
    assert not (target / "docker-compose.yml").exists()


def test_init_refuses_tracked_worktree_symlink_to_external_bundle(
    tmp_path,
    capsys,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "--quiet"], check=True)
    external = tmp_path / "external-bundle"
    external.mkdir()
    target = repo / "bundle"
    target.symlink_to(external, target_is_directory=True)
    subprocess.run(["git", "-C", str(repo), "add", "bundle"], check=True)

    assert commands.self_host_init(["--dir", str(target)]) == 1
    error = capsys.readouterr().err
    assert "Git-worktree symlink" in error
    assert list(external.iterdir()) == []


def test_protect_existing_refuses_insecure_secrets_mode(tmp_path, capsys):
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    password = (target / "secrets" / "db-password").read_bytes()
    (target / "secrets").chmod(0o755)

    assert (
        commands.self_host_init(
            [
                "--dir",
                str(target),
                "--protect-existing",
            ]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "mode 0700" in error
    assert "chmod 700" in error
    assert (target / "secrets" / "db-password").read_bytes() == password


def test_protect_existing_refuses_symlinked_database_secret(tmp_path, capsys):
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    password_path = target / "secrets" / "db-password"
    external = tmp_path / "external-password"
    password_path.replace(external)
    password_path.symlink_to(external)

    assert (
        commands.self_host_init(
            [
                "--dir",
                str(target),
                "--protect-existing",
            ]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "symlink instead of a regular file" in error
    assert external.read_bytes()
    assert password_path.is_symlink()


def test_protect_existing_refuses_exposed_database_secret(tmp_path, capsys):
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    password_path = target / "secrets" / "db-password"
    password_path.chmod(0o644)

    assert commands.self_host_init(["--dir", str(target), "--protect-existing"]) == 1
    error = capsys.readouterr().err
    assert "no group/world access" in error
    assert "chmod 600" in error


def test_protect_existing_refuses_symlinked_env(tmp_path, capsys):
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    env_path = target / ".env"
    external = tmp_path / "external-env"
    env_path.replace(external)
    env_path.symlink_to(external)

    assert (
        commands.self_host_init(
            [
                "--dir",
                str(target),
                "--protect-existing",
            ]
        )
        == 1
    )
    assert "symlink instead of a regular file" in capsys.readouterr().err
    assert env_path.is_symlink()


def test_force_replaces_env_symlink_without_touching_external_file(
    tmp_path,
    capsys,
):
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    env_path = target / ".env"
    external = tmp_path / "external-env"
    external.write_bytes(b"sentinel\n")
    env_path.unlink()
    env_path.symlink_to(external)

    assert (
        commands.self_host_init(
            [
                "--dir",
                str(target),
                "--force",
            ]
        )
        == 0
    )
    assert external.read_bytes() == b"sentinel\n"
    assert env_path.is_file()
    assert not env_path.is_symlink()


def test_existing_validation_rechecks_bundle_owner_control(tmp_path, monkeypatch):
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    real_euid = secure_layout.os.geteuid()
    monkeypatch.setattr(secure_layout.os, "geteuid", lambda: real_euid + 1)

    with pytest.raises(
        secure_layout.SecureLayoutError,
        match="owned by the current user",
    ):
        secure_layout.validate_existing_bundle_files(
            target,
            public_names=("docker-compose.yml", ".env"),
            secret_names=("db-password", "dsn"),
        )
