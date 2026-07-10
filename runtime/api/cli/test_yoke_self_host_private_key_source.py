"""Trust-boundary tests for GitHub App private-key source ingress."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.self_host import protection


_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
cHJpdmF0ZS1rZXk=
-----END RSA PRIVATE KEY-----
"""


def _init_bundle(tmp_path, capsys) -> Path:
    target = tmp_path / "bundle"
    assert commands.self_host_init(["--dir", str(target)]) == 0
    capsys.readouterr()
    return target


def _key_args(target: Path, source: Path) -> list[str]:
    return [
        "--dir",
        str(target),
        "--protect-existing",
        "--github-app-private-key",
        str(source),
    ]


def test_private_key_source_refuses_symlink(tmp_path, capsys):
    target = _init_bundle(tmp_path, capsys)
    real_source = tmp_path / "real.pem"
    real_source.write_text(_PRIVATE_KEY, encoding="utf-8")
    real_source.chmod(0o600)
    source = tmp_path / "source.pem"
    source.symlink_to(real_source)

    assert commands.self_host_init(_key_args(target, source)) == 1
    error = capsys.readouterr().err
    assert "safely open GitHub App private-key source" in error
    assert "chmod 600" in error
    assert not (target / "secrets" / "github-app-private-key.pem").exists()


def test_private_key_source_refuses_group_world_access(tmp_path, capsys):
    target = _init_bundle(tmp_path, capsys)
    source = tmp_path / "source.pem"
    source.write_text(_PRIVATE_KEY, encoding="utf-8")
    source.chmod(0o644)

    assert commands.self_host_init(_key_args(target, source)) == 1
    error = capsys.readouterr().err
    assert "group/world" in error
    assert "chmod 600" in error


def test_private_key_source_refuses_nonowner_metadata(tmp_path, monkeypatch):
    source = tmp_path / "source.pem"
    source.write_text(_PRIVATE_KEY, encoding="utf-8")
    source.chmod(0o600)
    real_euid = protection.os.geteuid()
    monkeypatch.setattr(protection.os, "geteuid", lambda: real_euid + 1)

    with pytest.raises(
        protection.SelfHostProtectionError,
        match="current-owner",
    ):
        protection._read_private_key_source(source)


def test_private_key_source_refuses_hardlink(tmp_path, capsys):
    target = _init_bundle(tmp_path, capsys)
    source = tmp_path / "source.pem"
    source.write_text(_PRIVATE_KEY, encoding="utf-8")
    source.chmod(0o600)
    (tmp_path / "second-link.pem").hardlink_to(source)

    assert commands.self_host_init(_key_args(target, source)) == 1
    assert "single-link regular file" in capsys.readouterr().err


def test_private_key_source_swap_after_open_reads_original_descriptor(
    tmp_path,
    capsys,
    monkeypatch,
):
    target = _init_bundle(tmp_path, capsys)
    source = tmp_path / "source.pem"
    source.write_text(_PRIVATE_KEY, encoding="utf-8")
    source.chmod(0o600)
    replacement = tmp_path / "replacement.pem"
    replacement.write_text("not a private key\n", encoding="utf-8")
    replacement.chmod(0o600)
    opened_source = tmp_path / "opened-source.pem"
    real_open = protection.os.open
    swapped = False

    def _open_then_swap(path, *args, **kwargs):
        nonlocal swapped
        descriptor = real_open(path, *args, **kwargs)
        if not swapped and Path(path) == source:
            source.replace(opened_source)
            replacement.replace(source)
            swapped = True
        return descriptor

    monkeypatch.setattr(protection.os, "open", _open_then_swap)
    assert commands.self_host_init(_key_args(target, source)) == 0

    installed = target / "secrets" / "github-app-private-key.pem"
    assert installed.read_text(encoding="utf-8") == _PRIVATE_KEY
    assert source.read_text(encoding="utf-8") == "not a private key\n"
