"""GitHub App private-key file ownership, encoding, and path policy."""

from __future__ import annotations

from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from yoke_core.domain import github_app_control_plane as control_plane
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_API_URL_ENV,
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
    GitHubAppControlPlaneConfigError,
    load_github_app_control_plane_config,
)


def test_control_plane_config_reads_owner_only_private_key(tmp_path: Path) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("test-private-key", encoding="utf-8")
    key_file.chmod(0o600)

    config = load_github_app_control_plane_config(
        {
            GITHUB_APP_ISSUER_ENV: "Iv1.control-plane",
            GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
            GITHUB_APP_API_URL_ENV: "https://github.example/api/v3",
        }
    )

    assert config.issuer == "Iv1.control-plane"
    assert config.private_key_pem == "test-private-key"
    assert config.endpoint.base_url == "https://github.example/api/v3"
    assert "test-private-key" not in repr(config)


def test_control_plane_config_rejects_group_readable_private_key(
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("test-private-key", encoding="utf-8")
    key_file.chmod(0o640)

    with pytest.raises(GitHubAppControlPlaneConfigError, match="owner-only"):
        load_github_app_control_plane_config(
            {
                GITHUB_APP_ISSUER_ENV: "Iv1.control-plane",
                GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
            }
        )


def test_control_plane_config_rejects_invalid_issuer_and_key_encoding(
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_bytes(b"\xff\xfe")
    key_file.chmod(0o600)
    with pytest.raises(GitHubAppControlPlaneConfigError, match="issuer"):
        load_github_app_control_plane_config(
            {
                GITHUB_APP_ISSUER_ENV: "Iv1.good\nInjected",
                GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
            }
        )
    with pytest.raises(GitHubAppControlPlaneConfigError, match="UTF-8"):
        load_github_app_control_plane_config(
            {
                GITHUB_APP_ISSUER_ENV: "Iv1.good",
                GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
            }
        )


def test_control_plane_config_accepts_root_owned_read_only_secret_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("test-private-key", encoding="utf-8")
    mounted_stat = SimpleNamespace(
        st_uid=0,
        st_mode=stat.S_IFREG | 0o444,
        st_size=len("test-private-key"),
    )
    monkeypatch.setattr(control_plane.os, "fstat", lambda descriptor: mounted_stat)
    monkeypatch.setattr(
        control_plane.os,
        "readlink",
        lambda path: "/run/secrets/yoke-github-app-private-key",
    )

    config = load_github_app_control_plane_config(
        {
            GITHUB_APP_ISSUER_ENV: "Iv1.control-plane",
            GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
        }
    )

    assert config.private_key_pem == "test-private-key"


def test_control_plane_config_rejects_root_owned_file_outside_runtime_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("test-private-key", encoding="utf-8")
    mounted_stat = SimpleNamespace(
        st_uid=0,
        st_mode=stat.S_IFREG | 0o444,
        st_size=len("test-private-key"),
    )
    monkeypatch.setattr(control_plane.os, "fstat", lambda descriptor: mounted_stat)
    monkeypatch.setattr(control_plane.os, "readlink", lambda path: str(key_file))

    with pytest.raises(GitHubAppControlPlaneConfigError, match="/run/secrets"):
        load_github_app_control_plane_config(
            {
                GITHUB_APP_ISSUER_ENV: "Iv1.control-plane",
                GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key_file),
            }
        )


def test_control_plane_config_rejects_private_key_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.pem"
    target.write_text("test-private-key", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "github-app.pem"
    link.symlink_to(target)

    with pytest.raises(GitHubAppControlPlaneConfigError, match="safely opened"):
        load_github_app_control_plane_config(
            {
                GITHUB_APP_ISSUER_ENV: "Iv1.control-plane",
                GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(link),
            }
        )
