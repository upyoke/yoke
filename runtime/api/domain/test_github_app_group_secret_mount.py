"""Dedicated-group GitHub App secret mount policy."""

from __future__ import annotations

from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from yoke_core.domain import github_app_control_plane as control_plane
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
    GitHubAppControlPlaneConfigError,
    load_github_app_control_plane_config,
)


def _patch_group_mount(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: int,
) -> None:
    mounted_stat = SimpleNamespace(
        st_uid=1000,
        st_gid=4321,
        st_mode=stat.S_IFREG | mode,
    )
    monkeypatch.setattr(control_plane.os, "fstat", lambda descriptor: mounted_stat)
    monkeypatch.setattr(
        control_plane.os,
        "readlink",
        lambda path: "/run/secrets/yoke-github-app-private-key",
    )
    monkeypatch.setattr(control_plane.os, "getegid", lambda: 101)
    monkeypatch.setattr(control_plane.os, "getgroups", lambda: [4321])


def _config(key_file: Path):
    return load_github_app_control_plane_config(
        {
            GITHUB_APP_ISSUER_ENV: "Iv1.control-plane",
            GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
        }
    )


def test_accepts_service_group_read_only_secret_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("test-private-key", encoding="utf-8")
    _patch_group_mount(monkeypatch, mode=0o640)

    assert _config(key_file).private_key_pem == "test-private-key"


def test_rejects_group_writable_secret_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("test-private-key", encoding="utf-8")
    _patch_group_mount(monkeypatch, mode=0o660)

    with pytest.raises(GitHubAppControlPlaneConfigError, match="group-read-only"):
        _config(key_file)
