"""Tests for ``yoke self-host init`` — the compose-bundle writer.

Pins the bundle file set, secret-file permissions, the no-clobber guard,
``--force`` rewrite semantics, knob overrides, and that the generated
password never reaches stdout/stderr or ``.env``.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.self_host import atomic_file
from yoke_cli.self_host import bundle
from yoke_cli.self_host import protection
from yoke_contracts.server_image import (
    DEFAULT_SERVER_IMAGE,
    PUBLISHED_SERVER_IMAGE_REPOSITORY,
)


@pytest.fixture()
def target(tmp_path) -> Path:
    return tmp_path / "server-bundle"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _password(target: Path) -> str:
    return (target / "secrets" / "db-password").read_text(encoding="utf-8").strip()


def test_init_writes_bundle_file_set_with_owner_only_secrets(target, capsys):
    assert commands.self_host_init(["--dir", str(target)]) == 0

    compose = (target / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgres:17" in compose
    assert "${YOKE_SERVER_IMAGE}" in compose
    assert "pg_isready" in compose
    assert "YOKE_PG_DSN_FILE" in compose
    assert "POSTGRES_PASSWORD_FILE" in compose

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert f"YOKE_SERVER_IMAGE={DEFAULT_SERVER_IMAGE}" in env_text
    assert "YOKE_API_PUBLISH=127.0.0.1:8765" in env_text

    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.splitlines() == [
        protection.GITIGNORE_MANAGED_BEGIN,
        "# Managed by Yoke; operator rules outside this block are preserved.",
        "/.env",
        "/secrets/",
        "/..env.lock",
        "/..env.*.tmp",
        "/.docker-compose.yml.lock",
        "/.docker-compose.yml.*.tmp",
        "/..gitignore.lock",
        "/..gitignore.*.tmp",
        protection.GITIGNORE_MANAGED_END,
    ]

    secrets_dir = target / "secrets"
    assert _mode(secrets_dir) == 0o700
    password = _password(target)
    assert len(password) == 64  # 32 bytes hex — no $ for compose to eat
    assert _mode(secrets_dir / "db-password") == 0o600
    dsn = (secrets_dir / "dsn").read_text(encoding="utf-8").strip()
    assert _mode(secrets_dir / "dsn") == 0o600
    assert "host=db" in dsn
    assert password in dsn
    assert list(secrets_dir.glob(".*.tmp")) == []
    for protected_path in (
        target / ".gitignore",
        target / "docker-compose.yml",
        target / ".env",
        secrets_dir / "db-password",
        secrets_dir / "dsn",
    ):
        assert _mode(atomic_file.target_lock_path(protected_path)) == 0o600

    out = capsys.readouterr()
    assert password not in out.out
    assert password not in out.err
    assert password not in env_text
    assert "docker compose up -d" in out.out
    assert "yoke connect" in out.out


def test_init_ships_browser_sign_in_wiring_disabled(target):
    """The OIDC door rides the bundle as commented-out opt-in blocks: the
    compose file passes the env knobs through (blank = disabled) and
    names a secret-file slot; .env documents the enable steps without
    activating anything."""
    assert commands.self_host_init(["--dir", str(target)]) == 0

    compose = (target / "docker-compose.yml").read_text(encoding="utf-8")
    assert "YOKE_OIDC_ISSUER: ${YOKE_OIDC_ISSUER:-}" in compose
    assert "YOKE_OIDC_CLIENT_SECRET_FILE: ${YOKE_OIDC_CLIENT_SECRET_FILE:-}" in compose
    # The secret mount stays commented until the operator creates the file.
    assert "#- yoke-oidc-client-secret" in compose
    assert "#yoke-oidc-client-secret:" in compose

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "#YOKE_OIDC_ISSUER=" in env_text
    assert "#YOKE_OIDC_CLIENT_SECRET_FILE=" in env_text
    # No active (uncommented) OIDC assignment ships by default.
    assert not any(line.startswith("YOKE_OIDC_") for line in env_text.splitlines())


def test_init_ships_github_app_secret_wiring_disabled(target):
    assert commands.self_host_init(["--dir", str(target)]) == 0

    compose = (target / "docker-compose.yml").read_text(encoding="utf-8")
    assert "YOKE_GITHUB_APP_ISSUER: ${YOKE_GITHUB_APP_ISSUER:-}" in compose
    assert "YOKE_GITHUB_APP_CLIENT_ID: ${YOKE_GITHUB_APP_CLIENT_ID:-}" in compose
    assert "YOKE_GITHUB_APP_SLUG: ${YOKE_GITHUB_APP_SLUG:-}" in compose
    assert "YOKE_GITHUB_APP_ID: ${YOKE_GITHUB_APP_ID:-}" in compose
    assert "YOKE_GITHUB_APP_WEB_URL: ${YOKE_GITHUB_APP_WEB_URL:-}" in compose
    assert "YOKE_GITHUB_APP_PRIVATE_KEY_FILE:" in compose
    assert "#- yoke-github-app-private-key" in compose
    assert "#yoke-github-app-private-key:" in compose

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "#YOKE_GITHUB_APP_ISSUER=" in env_text
    assert "#YOKE_GITHUB_APP_API_URL=https://api.github.com" in env_text
    assert "#YOKE_GITHUB_APP_WEB_URL=https://github.com" in env_text
    assert "#YOKE_GITHUB_APP_ID=123456" in env_text
    assert "#YOKE_GITHUB_APP_CLIENT_ID=" in env_text
    assert "#YOKE_GITHUB_APP_SLUG=" in env_text
    assert "#YOKE_GITHUB_APP_PRIVATE_KEY_FILE=" in env_text
    assert not any(
        line.startswith("YOKE_GITHUB_APP_") for line in env_text.splitlines()
    )
    assert "cp /secure/path" not in env_text
    assert "--protect-existing" in env_text
    assert "--github-app-private-key" in env_text


def test_init_uses_self_host_only_root_bootstrap_for_core_secrets(target):
    assert commands.self_host_init(["--dir", str(target)]) == 0

    compose = (target / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'user: "0:0"' in compose
    assert (
        'entrypoint: ["python", "-m", '
        '"yoke_core.tools.self_host_server_bootstrap"]' in compose
    )
    assert "command: []" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "cap_add:\n      - CHOWN\n      - SETGID\n      - SETUID" in compose
    assert "security_opt:\n      - no-new-privileges:true" in compose
    assert (
        "- yoke_core.tools.self_host_server_bootstrap\n        - --healthcheck"
        in compose
    )
    assert "YOKE_PG_DSN_FILE: /run/secrets/yoke-db-dsn" in compose
    assert "- /run/yoke-runtime-secrets:mode=0700" in compose


def test_init_json_report_omits_secrets(target, capsys):
    assert commands.self_host_init(["--dir", str(target), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["image"] == DEFAULT_SERVER_IMAGE
    assert str(target / ".gitignore") in report["files"]
    assert _password(target) not in json.dumps(report)


def test_init_port_and_image_overrides(target):
    assert (
        commands.self_host_init(
            [
                "--dir",
                str(target),
                "--port",
                "9000",
                "--image",
                "example.test/yoke-server:pinned",
            ]
        )
        == 0
    )
    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "YOKE_API_PUBLISH=127.0.0.1:9000" in env_text
    assert "YOKE_SERVER_IMAGE=example.test/yoke-server:pinned" in env_text


def test_init_refuses_clobber_without_force(target, capsys):
    assert commands.self_host_init(["--dir", str(target)]) == 0
    first_password = _password(target)
    capsys.readouterr()

    assert commands.self_host_init(["--dir", str(target)]) == 1
    err = capsys.readouterr().err
    assert "--force" in err
    assert first_password not in err
    assert _password(target) == first_password

    assert commands.self_host_init(["--dir", str(target), "--force"]) == 0
    assert _password(target) != first_password


def test_default_directory_lands_under_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = bundle.write_bundle()
    assert report["directory"] == str((tmp_path / bundle.DEFAULT_BUNDLE_DIR).resolve())


def test_published_image_constant_shape():
    assert DEFAULT_SERVER_IMAGE.startswith(PUBLISHED_SERVER_IMAGE_REPOSITORY)
    assert PUBLISHED_SERVER_IMAGE_REPOSITORY.startswith("ghcr.io/")


def test_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["self-host", "init", "--json"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is commands.self_host_init
    assert remaining == ["--json"]
