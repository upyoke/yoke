"""CLI round-trip tests for the machine-config writer subcommands."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_config_write_test_support import (
    _assert_auth_token_imported as _assert_auth_token_imported,
    _assert_dsn_imported as _assert_dsn_imported,
    _payload as _payload,
    _secret_path as _secret_path,
    _seed as _seed,
    cfg as cfg,
)


from yoke_cli import main as yoke_operations_cli


def test_connection_set_then_env_use_round_trip(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    _seed(cfg, tmp_path, "stage")
    capsys.readouterr()

    rc = yoke_operations_cli.main(["env", "use", "stage", "--config", str(cfg)])

    assert rc == 0
    assert "active env: stage" in capsys.readouterr().out
    assert _payload(cfg)["active_env"] == "stage"


def test_connection_set_https_direct_token_infers_transport(cfg, capsys) -> None:
    secret = "yoke_v1_prod_secret"

    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            "prod",
            secret,
            "--api-url",
            "https://api.example",
            "--config",
            str(cfg),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    _assert_auth_token_imported(cfg, "prod", secret, captured)
    assert _payload(cfg)["connections"]["prod"]["transport"] == "https"


def test_connection_set_protected_flags_round_trip(cfg, capsys) -> None:
    secret = "yoke_v1_prod_secret"

    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            "prod",
            secret,
            "--protected",
            "--api-url",
            "https://api.example",
            "--config",
            str(cfg),
        ]
    )
    assert rc == 0
    capsys.readouterr()
    assert _payload(cfg)["connections"]["prod"]["protected"] is True

    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            "prod",
            "--unprotected",
            "--config",
            str(cfg),
        ]
    )

    assert rc == 0
    capsys.readouterr()
    assert _payload(cfg)["connections"]["prod"]["protected"] is False


def test_connection_set_protected_flags_are_mutually_exclusive(cfg, capsys) -> None:
    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            "prod",
            "--transport",
            "https",
            "--protected",
            "--unprotected",
            "--config",
            str(cfg),
        ]
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "--protected" in err
    assert "--unprotected" in err


def test_connection_set_positional_dsn_infers_local_postgres_transport(
    cfg, capsys
) -> None:
    dsn = "postgresql://admin:secret@localhost/yoke"

    rc = yoke_operations_cli.main(
        [
            "connection",
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
    assert _payload(cfg)["connections"]["local"]["transport"] == "local-postgres"
    assert _payload(cfg)["connections"]["local"]["protected"] is False


def test_env_use_unknown_env_exits_nonzero(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")

    rc = yoke_operations_cli.main(["env", "use", "ghost", "--config", str(cfg)])

    assert rc == 1
    assert "prod" in capsys.readouterr().err


def test_connection_set_positional_dsn_uses_existing_local_postgres_transport(
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
    dsn = "postgresql://new-secret@localhost/yoke"

    rc = yoke_operations_cli.main(
        [
            "connection",
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


def test_writer_set_connection_replace_drops_stale_transport_keys(
    cfg,
    tmp_path,
) -> None:
    from yoke_cli.config import writer

    _seed(cfg, tmp_path, "local")  # https-shaped: api_url + token credential
    result = writer.set_connection(
        "local",
        transport="local-postgres",
        dsn="postgresql://replaced@localhost/yoke",
        protected=False,
        replace=True,
        path=str(cfg),
    )

    entry = _payload(cfg)["connections"]["local"]
    assert entry["transport"] == "local-postgres"
    assert entry["protected"] is False
    assert entry["credential_source"]["kind"] == "dsn_file"
    # True replace: the https entry's api_url and token ref are gone.
    assert set(entry) == {"transport", "protected", "credential_source"}
    assert result["connection"] == entry


def test_invalid_write_is_refused_with_contract_codes(cfg, capsys) -> None:
    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            "stage",
            "--transport",
            "https",
            "--config",
            str(cfg),
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "api_url_required" in err
    assert not cfg.exists()
