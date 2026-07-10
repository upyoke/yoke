"""CLI round-trip tests for the machine-config writer subcommands."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "machine-home" / "config.json"


def _seed(cfg: Path, tmp_path: Path, env: str) -> None:
    token = tmp_path / f"{env}.token"
    token.write_text("tok\n")
    rc = yoke_operations_cli.main([
        "connection", "set", env,
        "--transport", "https",
        "--api-url", f"https://api.{env}.example",
        "--token-file", str(token),
        "--config", str(cfg),
    ])
    assert rc == 0


def _payload(cfg: Path) -> dict:
    return json.loads(cfg.read_text())


def _secret_path(cfg: Path, env: str, suffix: str = "token") -> Path:
    return cfg.parent / "secrets" / f"{env}.{suffix}"


def _assert_auth_token_imported(
    cfg: Path, env: str, secret: str, captured
) -> None:
    token_path = _secret_path(cfg, env)
    assert token_path.is_file()
    assert token_path.read_text() == secret + "\n"
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert token_path.parent.stat().st_mode & 0o777 == 0o700

    payload = _payload(cfg)
    assert payload["connections"][env]["credential_source"] == {
        "kind": "token_file", "path": str(token_path),
    }
    assert secret not in cfg.read_text()
    assert secret not in captured.out
    assert secret not in captured.err


def _assert_dsn_imported(cfg: Path, env: str, dsn: str, captured) -> None:
    dsn_path = _secret_path(cfg, env, "dsn")
    assert dsn_path.is_file()
    assert dsn_path.read_text() == dsn + "\n"
    assert dsn_path.stat().st_mode & 0o777 == 0o600
    assert dsn_path.parent.stat().st_mode & 0o777 == 0o700

    payload = _payload(cfg)
    assert payload["connections"][env]["credential_source"] == {
        "kind": "dsn_file", "path": str(dsn_path),
    }
    assert dsn not in cfg.read_text()
    assert dsn not in captured.out
    assert dsn not in captured.err


def test_connection_set_then_env_use_round_trip(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    _seed(cfg, tmp_path, "stage")
    capsys.readouterr()

    rc = yoke_operations_cli.main(["env", "use", "stage", "--config", str(cfg)])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["active_env"] == "stage"
    assert _payload(cfg)["active_env"] == "stage"


def test_connection_set_https_direct_token_infers_transport(
    cfg, capsys
) -> None:
    secret = "yoke_v1_prod_secret"

    rc = yoke_operations_cli.main([
        "connection", "set", "prod", secret,
        "--api-url", "https://api.example",
        "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "prod", secret, captured)
    assert _payload(cfg)["connections"]["prod"]["transport"] == "https"


def test_connection_set_prod_flags_round_trip(cfg, capsys) -> None:
    secret = "yoke_v1_prod_secret"

    rc = yoke_operations_cli.main([
        "connection", "set", "prod", secret,
        "--prod",
        "--api-url", "https://api.example",
        "--config", str(cfg),
    ])
    assert rc == 0
    capsys.readouterr()
    assert _payload(cfg)["connections"]["prod"]["prod"] is True

    rc = yoke_operations_cli.main([
        "connection", "set", "prod", "--non-prod", "--config", str(cfg),
    ])

    assert rc == 0
    capsys.readouterr()
    assert _payload(cfg)["connections"]["prod"]["prod"] is False


def test_connection_set_prod_flags_are_mutually_exclusive(cfg, capsys) -> None:
    rc = yoke_operations_cli.main([
        "connection", "set", "prod",
        "--transport", "https",
        "--prod",
        "--non-prod",
        "--config", str(cfg),
    ])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--prod" in err
    assert "--non-prod" in err


def test_connection_set_positional_dsn_infers_local_postgres_transport(
    cfg, capsys
) -> None:
    dsn = "postgresql://admin:secret@localhost/yoke"

    rc = yoke_operations_cli.main([
        "connection", "set", "local", dsn, "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_dsn_imported(cfg, "local", dsn, captured)
    assert _payload(cfg)["connections"]["local"]["transport"] == "local-postgres"
    assert _payload(cfg)["connections"]["local"]["prod"] is False


def test_env_use_unknown_env_exits_nonzero(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")

    rc = yoke_operations_cli.main(["env", "use", "ghost", "--config", str(cfg)])

    assert rc == 1
    assert "prod" in capsys.readouterr().err


def test_auth_set_token_file_rotates_credential(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "stage")
    rotated = tmp_path / "rotated.token"
    secret = "yoke_v1_rotated_secret"
    rotated.write_text(secret + "\n")
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "auth", "set", "stage", "--token-file", str(rotated),
        "--config", str(cfg),
    ])

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

    rc = yoke_operations_cli.main([
        "auth", "set", "stage", secret, "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "stage", secret, captured)


def test_connection_set_positional_dsn_uses_existing_local_postgres_transport(
    cfg, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "connection", "set", "local",
        "--transport", "local-postgres",
        "--dsn", "postgresql://old-secret@localhost/yoke",
        "--config", str(cfg),
    ])
    assert rc == 0
    capsys.readouterr()
    dsn = "postgresql://new-secret@localhost/yoke"

    rc = yoke_operations_cli.main([
        "connection", "set", "local", dsn, "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_dsn_imported(cfg, "local", dsn, captured)


def test_writer_set_connection_replace_drops_stale_transport_keys(
    cfg, tmp_path,
) -> None:
    from yoke_cli.config import writer

    _seed(cfg, tmp_path, "local")  # https-shaped: api_url + token credential
    result = writer.set_connection(
        "local",
        transport="local-postgres",
        dsn="postgresql://replaced@localhost/yoke",
        prod=False,
        replace=True,
        path=str(cfg),
    )

    entry = _payload(cfg)["connections"]["local"]
    assert entry["transport"] == "local-postgres"
    assert entry["prod"] is False
    assert entry["credential_source"]["kind"] == "dsn_file"
    # True replace: the https entry's api_url and token ref are gone.
    assert set(entry) == {"transport", "prod", "credential_source"}
    assert result["connection"] == entry


def test_auth_set_positional_dsn_uses_existing_local_postgres_transport(
    cfg, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "connection", "set", "local",
        "--transport", "local-postgres",
        "--dsn", "postgresql://old-secret@localhost/yoke",
        "--config", str(cfg),
    ])
    assert rc == 0
    capsys.readouterr()
    dsn = "postgresql://rotated-secret@localhost/yoke"

    rc = yoke_operations_cli.main([
        "auth", "set", "local", dsn, "--config", str(cfg),
    ])

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

    rc = yoke_operations_cli.main([
        "auth", "set", "stage", "--token-stdin", "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "stage", secret, captured)


def test_project_register_maps_checkout(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "project", "register", str(repo),
        "--project-id", "7",
        "--board-scope", "all",
        "--config", str(cfg),
    ])

    assert rc == 0
    payload = json.loads(cfg.read_text())
    checkout = json.loads(capsys.readouterr().out)["checkout"]
    assert payload["projects"] == [
        {"checkout": checkout, "project_id": 7, "env": "prod",
         "board": {"scope": "all"}},
    ]


def test_stamp_project_env_stamps_untagged_entries(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    # A pre-existing untagged (legacy) mapping in the old object shape.
    payload = json.loads(cfg.read_text())
    payload["projects"] = {"/checkout/legacy": {"project_id": 3}}
    cfg.write_text(json.dumps(payload), encoding="utf-8")
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "config", "stamp-project-env", "--config", str(cfg),
    ])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["env"] == "prod"
    assert [row["checkout"] for row in result["stamped"]] == ["/checkout/legacy"]
    assert json.loads(cfg.read_text())["projects"] == [
        {"checkout": "/checkout/legacy", "project_id": 3, "env": "prod"},
    ]


def test_invalid_write_is_refused_with_contract_codes(cfg, capsys) -> None:
    rc = yoke_operations_cli.main([
        "connection", "set", "stage", "--transport", "https",
        "--config", str(cfg),
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "api_url_required" in err
    assert not cfg.exists()
