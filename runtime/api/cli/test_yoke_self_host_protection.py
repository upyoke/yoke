"""Secret-protection and credential-ingress tests for self-host bundles."""

from __future__ import annotations

from pathlib import Path
import stat
import subprocess

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.self_host import atomic_file
from yoke_cli.self_host import protection


_PRIVATE_KEY_ONE = """-----BEGIN RSA PRIVATE KEY-----
b2xkLWtleQ==
-----END RSA PRIVATE KEY-----
"""
_PRIVATE_KEY_TWO = """-----BEGIN PRIVATE KEY-----
bmV3LWtleQ==
-----END PRIVATE KEY-----
"""


@pytest.fixture()
def target(tmp_path) -> Path:
    return tmp_path / "server-bundle"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _password(target: Path) -> str:
    return (target / "secrets" / "db-password").read_text(encoding="utf-8").strip()


def test_init_preserves_operator_gitignore_and_rules_ignore_secrets(
    target,
    capsys,
):
    target.mkdir(parents=True)
    gitignore = target / ".gitignore"
    operator_text = "# Operator rules\n*.local\n!keep.local\n"
    gitignore.write_text(operator_text, encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(target.parent), "init", "--quiet"],
        check=True,
    )

    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()

    merged = gitignore.read_text(encoding="utf-8")
    assert merged.startswith(operator_text)
    assert merged.count(protection.GITIGNORE_MANAGED_BEGIN) == 1
    assert merged.count(protection.GITIGNORE_MANAGED_END) == 1
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(target.parent),
                "check-ignore",
                "--quiet",
                str(target / ".env"),
            ],
            check=False,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(target.parent),
                "check-ignore",
                "--quiet",
                str(atomic_file.target_lock_path(gitignore)),
            ],
            check=False,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(target.parent),
                "check-ignore",
                "--quiet",
                str(target / "secrets" / "future-key.pem"),
            ],
            check=False,
        ).returncode
        == 0
    )


def test_protect_existing_is_idempotent_and_preserves_bundle(target, capsys):
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    gitignore = target / ".gitignore"
    gitignore.write_text("# operator-owned\n*.backup\n", encoding="utf-8")
    preserved_paths = (
        target / "docker-compose.yml",
        target / ".env",
        target / "secrets" / "db-password",
        target / "secrets" / "dsn",
    )
    before = {path: path.read_bytes() for path in preserved_paths}

    args = ["--dir", str(target), "--protect-existing"]
    assert commands.self_host_init(args) == 0
    first = gitignore.read_bytes()
    output = capsys.readouterr().out
    assert "preserved (not regenerated)" in output
    assert commands.self_host_init(args) == 0
    assert gitignore.read_bytes() == first
    assert {path: path.read_bytes() for path in preserved_paths} == before
    assert gitignore.read_text(encoding="utf-8").startswith(
        "# operator-owned\n*.backup\n"
    )
    assert (
        gitignore.read_text(encoding="utf-8").count(protection.GITIGNORE_MANAGED_BEGIN)
        == 1
    )


def test_protect_existing_refuses_already_tracked_sensitive_files(
    target,
    capsys,
):
    subprocess.run(
        ["git", "-C", str(target.parent), "init", "--quiet"],
        check=True,
    )
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    subprocess.run(
        [
            "git",
            "-C",
            str(target.parent),
            "add",
            "--force",
            "--",
            str(target / ".env"),
            str(target / "secrets" / "db-password"),
        ],
        check=True,
    )
    before = (target / "secrets" / "db-password").read_bytes()

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
    assert "Git already tracks sensitive" in error
    assert "Ignore rules do not untrack" in error
    assert "rotate any credentials" in error
    assert (target / "secrets" / "db-password").read_bytes() == before


def test_github_app_private_key_rotation_is_atomic_and_preserves_db_secret(
    target,
    tmp_path,
    capsys,
    monkeypatch,
):
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    password = _password(target)
    source_one = tmp_path / "github-app-one.pem"
    source_two = tmp_path / "github-app-two.pem"
    source_one.write_text(_PRIVATE_KEY_ONE, encoding="utf-8")
    source_two.write_text(_PRIVATE_KEY_TWO, encoding="utf-8")
    source_one.chmod(0o600)
    source_two.chmod(0o600)
    key_path = target / "secrets" / "github-app-private-key.pem"
    replacements = []
    fsync_descriptors = []
    real_replace = atomic_file.os.replace
    real_fsync = atomic_file.os.fsync

    def _record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    def _record_fsync(descriptor):
        fsync_descriptors.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(atomic_file.os, "replace", _record_replace)
    monkeypatch.setattr(atomic_file.os, "fsync", _record_fsync)

    base_args = ["--dir", str(target), "--protect-existing"]
    assert (
        commands.self_host_init(
            [
                *base_args,
                "--github-app-private-key",
                str(source_one),
            ]
        )
        == 0
    )
    assert key_path.read_text(encoding="utf-8") == _PRIVATE_KEY_ONE
    assert _mode(key_path) == 0o600
    assert (
        commands.self_host_init(
            [
                *base_args,
                "--github-app-private-key",
                str(source_two),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "installed atomically as mode 0600" in output
    assert key_path.read_text(encoding="utf-8") == _PRIVATE_KEY_TWO
    assert _mode(key_path) == 0o600
    assert _password(target) == password
    assert list((target / "secrets").glob(".*.tmp")) == []
    assert len(replacements) == 2
    assert all(
        source.parent == destination.parent for source, destination in replacements
    )
    assert all(destination == key_path for _, destination in replacements)
    assert len(fsync_descriptors) >= 4
    assert _mode(atomic_file.target_lock_path(key_path)) == 0o600
    assert _PRIVATE_KEY_ONE not in output
    assert _PRIVATE_KEY_TWO not in output


def test_github_app_private_key_rejects_invalid_source_without_replacement(
    target,
    tmp_path,
    capsys,
):
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    valid = tmp_path / "valid.pem"
    invalid = tmp_path / "invalid.pem"
    valid.write_text(_PRIVATE_KEY_ONE, encoding="utf-8")
    invalid.write_text("not a private key\n", encoding="utf-8")
    valid.chmod(0o600)
    invalid.chmod(0o600)
    args = ["--dir", str(target), "--protect-existing"]
    assert (
        commands.self_host_init(
            [
                *args,
                "--github-app-private-key",
                str(valid),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        commands.self_host_init(
            [
                *args,
                "--github-app-private-key",
                str(invalid),
            ]
        )
        == 1
    )
    assert "not an unencrypted PEM private key" in capsys.readouterr().err
    assert (target / "secrets" / "github-app-private-key.pem").read_text(
        encoding="utf-8"
    ) == _PRIVATE_KEY_ONE
    assert list((target / "secrets").glob(".*.tmp")) == []


def test_atomic_replace_failure_preserves_existing_secret(tmp_path, monkeypatch):
    target = tmp_path / "secret"
    target.write_bytes(b"original\n")
    target.chmod(0o600)

    def _fail_replace(_source, _destination):
        raise OSError("injected replacement failure")

    monkeypatch.setattr(atomic_file.os, "replace", _fail_replace)
    with pytest.raises(
        protection.SelfHostProtectionError,
        match="injected replacement failure",
    ):
        protection.atomic_replace_bytes(target, b"replacement\n", mode=0o600)

    assert target.read_bytes() == b"original\n"
    assert _mode(target) == 0o600
    assert list(tmp_path.glob(".*.tmp")) == []


def test_init_refuses_gitignore_symlink_without_touching_target(
    target,
    tmp_path,
    capsys,
):
    target.mkdir()
    operator_file = tmp_path / "operator-ignore"
    operator_file.write_text("operator-owned\n", encoding="utf-8")
    (target / ".gitignore").symlink_to(operator_file)

    assert commands.self_host_init(["--dir", str(target)]) == 1
    error = capsys.readouterr().err
    assert "safely read operator gitignore" in error
    assert operator_file.read_text(encoding="utf-8") == "operator-owned\n"
    assert not (target / ".env").exists()
    assert _mode(target / "secrets") == 0o700
