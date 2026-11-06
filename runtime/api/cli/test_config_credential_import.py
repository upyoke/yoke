"""Credential imports preserve machine config and keep secret values private."""

from __future__ import annotations

import io


from yoke_cli import main as yoke_operations_cli


from runtime.api.cli.yoke_operations_cli_config_write_test_support import (
    cfg as cfg,
    _seed,
    _assert_auth_token_imported,
    _assert_dsn_imported,
)


def test_auth_set_token_file_rotates_credential(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "stage")
    rotated = tmp_path / "rotated.token"
    secret = "yoke_v1_rotated_secret"
    rotated.write_text(secret + "\n")
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "auth",
            "set",
            "stage",
            "--token-file",
            str(rotated),
            "--config",
            str(cfg),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "stage", secret, captured)
    assert str(rotated) not in cfg.read_text()


def test_auth_set_positional_token_imports_without_leaking(
    cfg, tmp_path, capsys
) -> None:
    _seed(cfg, tmp_path, "stage")
    secret = "yoke_v1_cli_arg_secret"
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "auth",
            "set",
            "stage",
            secret,
            "--config",
            str(cfg),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "stage", secret, captured)


def test_auth_set_positional_dsn_uses_existing_local_postgres_transport(
    cfg, capsys
) -> None:
    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            "local",
            "--transport",
            "local-postgres",
            "--dsn",
            "postgresql://old-secret@localhost/yoke",
            "--config",
            str(cfg),
        ]
    )
    assert rc == 0
    capsys.readouterr()
    dsn = "postgresql://rotated-secret@localhost/yoke"

    rc = yoke_operations_cli.main(
        [
            "auth",
            "set",
            "local",
            dsn,
            "--config",
            str(cfg),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    _assert_dsn_imported(cfg, "local", dsn, captured)


def test_auth_set_token_stdin_imports_without_leaking(
    cfg, tmp_path, capsys, monkeypatch
) -> None:
    _seed(cfg, tmp_path, "stage")
    secret = "yoke_v1_stdin_secret"
    monkeypatch.setattr("sys.stdin", io.StringIO(secret + "\n"))
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "auth",
            "set",
            "stage",
            "--token-stdin",
            "--config",
            str(cfg),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "stage", secret, captured)
