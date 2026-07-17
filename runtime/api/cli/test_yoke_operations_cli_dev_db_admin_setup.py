"""CLI tests for ``yoke dev db-admin setup``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


def _identity_response(
    database: str,
    *,
    columns=None,
    rows=None,
    truncated: bool = False,
) -> FunctionCallResponse:
    selected_rows = [[database]] if rows is None else rows
    return FunctionCallResponse(
        success=True,
        function="db.read.run",
        version="v1",
        result={
            "columns": ["current_database"] if columns is None else columns,
            "rows": selected_rows,
            "row_count": len(selected_rows),
            "row_cap": 100,
            "truncated": truncated,
            "statement_timeout_ms": 5000,
        },
    )


def test_registry_and_inventory_track_dev_db_admin_setup() -> None:
    from yoke_cli import operation_inventory as inv
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("dev", "db-admin", "setup") not in SUBCOMMAND_REGISTRY
    assert ("dev", "db-admin", "setup") in TOOL_SHAPED_SUBCOMMANDS
    entry = inv.lookup("yoke dev db-admin setup")
    assert entry is not None
    assert entry.status == inv.PERMANENT
    assert entry.reason == inv.REASON_TOOL_SHAPED


def test_dev_db_admin_setup_dry_run_plans_without_resolving_secret(
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )
    monkeypatch.setattr(
        config,
        "_select_control_plane_env",
        lambda env_name, **_kwargs: env_name,
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda control_plane_env, **_kwargs: "yoke_tenant_4",
    )
    monkeypatch.setattr(
        config,
        "_resolve_environment_database_binding",
        lambda *_args, **_kwargs: pytest.fail("dry-run resolved cloud binding"),
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "stage",
            "--dry-run",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "dev.db_admin.setup"
    assert payload["applied"] is False
    assert payload["plan"]["admin_env"] == "stage-db-admin"
    assert payload["plan"]["postgres"]["host"] == "127.0.0.1"
    assert payload["plan"]["postgres"]["port"] == 6548
    assert payload["declared_deploy_database"] == "yoke_stage"
    assert payload["control_plane_database"] == "yoke_tenant_4"
    assert payload["control_plane_env"] == "stage"
    assert payload["plan"]["superseded_secret_path"].endswith(
        "secrets/yoke-stage-db-admin.dsn"
    )


def test_dev_db_admin_setup_apply_uses_managed_secret_and_removes_snapshot(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    config_path = machine_home / "config.json"
    secret_path = machine_home / "secrets" / "yoke-stage-db-admin.dsn"
    secret_path.parent.mkdir(mode=0o700, parents=True)
    secret_path.write_text("stale-password-snapshot\n", encoding="utf-8")
    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )
    monkeypatch.setattr(
        config,
        "_select_control_plane_env",
        lambda env_name, **_kwargs: env_name,
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda control_plane_env, **_kwargs: "yoke_tenant_4",
    )
    monkeypatch.setattr(
        config,
        "_resolve_environment_database_binding",
        lambda env, emit=None: (
            SimpleNamespace(
                host="stage.cluster.internal",
                port=5432,
            ),
            {
                "databaseClusterEndpoint": "stage.cluster.internal",
                "databaseSecretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-stage"
                ),
            },
        ),
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "stage",
            "--config",
            str(config_path),
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "stale-password-snapshot" not in captured.out
    assert "stale-password-snapshot" not in captured.err
    payload = json.loads(captured.out)
    assert payload["applied"] is True
    assert payload["superseded_dsn_snapshot_removed"] is True
    assert not secret_path.exists()
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    entry = config_payload["connections"]["stage-db-admin"]
    assert entry["transport"] == "local-postgres"
    assert entry["prod"] is False
    assert entry["credential_source"] == {
        "kind": "aws_secrets_manager",
        "secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-stage"
        ),
        "region": "us-east-1",
        "project": "yoke",
    }
    assert entry["postgres"] == {
        "host": "127.0.0.1",
        "port": 6548,
        "tunnel": {
            "kind": "ssh",
            "bastion": "ubuntu@origin.stage.example.com",
            "identity_file": "/tmp/yoke-stage.pem",
            "remote_host": "stage.cluster.internal",
            "remote_port": 5432,
        },
    }
    assert entry["authority"]["location"] == {
        "stack": "yoke-stage",
        "region": "us-east-1",
        "database_name": "yoke_tenant_4",
    }


def test_dev_db_admin_setup_can_mark_production_admin_authority(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    config_path = machine_home / "config.json"
    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )
    monkeypatch.setattr(
        config,
        "_select_control_plane_env",
        lambda env_name, **_kwargs: env_name,
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda control_plane_env, **_kwargs: "yoke_tenant_4",
    )
    monkeypatch.setattr(
        config,
        "_resolve_environment_database_binding",
        lambda env, emit=None: (
            SimpleNamespace(host="prod.cluster.internal", port=5432),
            {
                "databaseClusterEndpoint": "prod.cluster.internal",
                "databaseSecretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-prod"
                ),
            },
        ),
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "prod",
            "--prod",
            "--config",
            str(config_path),
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["connections"]["prod-db-admin"]["prod"] is True


def test_dev_db_admin_setup_refuses_render_only(monkeypatch, capsys) -> None:
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(
            project=project,
            env_name=env_name,
            activation_state="render_only",
        ),
    )
    monkeypatch.setattr(
        config,
        "_select_control_plane_env",
        lambda env_name, **_kwargs: env_name,
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda control_plane_env, **_kwargs: "yoke_tenant_4",
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "stage",
            "--yes",
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "render_only" in err
    assert "stage-db-admin" in err


def test_control_plane_identity_uses_explicit_named_https_not_active_local(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    config_path = tmp_path / "custom-config.json"
    token_path = tmp_path / "tenant.token"
    token_path.write_text("sensitive-token\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local-admin",
                "connections": {
                    "local-admin": {
                        "transport": "local-postgres",
                        "postgres": {"host": "127.0.0.1", "port": 5432},
                    },
                    "tenant-prod": {
                        "transport": "https",
                        "api_url": "https://tenant.example.com",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(token_path),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    observed = {}

    def relay(request, connection):
        observed["request"] = request
        observed["connection"] = connection
        return _identity_response("yoke_tenant_4")

    monkeypatch.setattr(config.https_transport, "relay_https", relay)

    selected = config._select_control_plane_env(
        "prod",
        control_plane_env="tenant-prod",
        config_path=config_path,
    )
    database = config._resolve_control_plane_database(
        selected,
        config_path=config_path,
    )

    assert selected == "tenant-prod"
    assert database == "yoke_tenant_4"
    assert observed["connection"].env == "tenant-prod"
    assert observed["request"].function == "db.read.run"
    assert observed["request"].payload == {
        "sql": "SELECT current_database()"
    }


def test_default_control_plane_env_requires_same_label_https(
    tmp_path: Path,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "tenant-prod",
                "connections": {
                    "prod": {
                        "transport": "local-postgres",
                        "postgres": {"host": "127.0.0.1", "port": 5432},
                    },
                    "tenant-prod": {
                        "transport": "https",
                        "api_url": "https://tenant.example.com",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(config.DbAdminSetupError, match="not HTTPS"):
        config._select_control_plane_env(
            "prod",
            control_plane_env=None,
            config_path=config_path,
        )


def test_control_plane_binding_refusal_does_not_write_custom_config(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    config_path = tmp_path / "custom-config.json"
    original = {
        "schema_version": 1,
        "active_env": "local-admin",
        "connections": {
            "local-admin": {
                "transport": "local-postgres",
                "postgres": {"host": "127.0.0.1", "port": 5432},
            }
        },
    }
    config_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "prod",
            "--control-plane-env",
            "local-admin",
            "--config",
            str(config_path),
            "--yes",
        ]
    )

    assert rc == 1
    assert "not HTTPS" in capsys.readouterr().err
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


def test_control_plane_identity_redacts_transport_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoke_cli.config import db_admin_setup as config
    from yoke_cli.transport.https import HttpsConnection

    token = "sensitive-token"
    monkeypatch.setattr(
        config.https_transport,
        "resolve_https_connection",
        lambda path, explicit_env=None: HttpsConnection(
            api_url="https://tenant.example.com",
            token=token,
            env=explicit_env or "",
        ),
    )
    monkeypatch.setattr(
        config.https_transport,
        "relay_https",
        lambda request, connection: (_ for _ in ()).throw(
            RuntimeError(f"transport rejected {token}")
        ),
    )

    with pytest.raises(config.DbAdminSetupError) as caught:
        config._resolve_control_plane_database(
            "tenant-prod",
            config_path=tmp_path / "custom-config.json",
        )

    assert token not in str(caught.value)
    assert "<redacted>" in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        _identity_response("yoke_tenant_4", columns=["database"]),
        _identity_response("yoke_tenant_4", rows=[]),
        _identity_response("", rows=[[""]]),
        _identity_response("yoke_tenant_4", rows=[["one"], ["two"]]),
        _identity_response("yoke_tenant_4", truncated=True),
        FunctionCallResponse(
            success=False,
            function="db.read.run",
            version="v1",
            error=FunctionError(code="permission_denied", message="denied"),
        ),
    ],
)
def test_control_plane_identity_refuses_non_exact_response(
    tmp_path: Path,
    monkeypatch,
    response: FunctionCallResponse,
) -> None:
    from yoke_cli.config import db_admin_setup as config
    from yoke_cli.transport.https import HttpsConnection

    monkeypatch.setattr(
        config.https_transport,
        "resolve_https_connection",
        lambda path, explicit_env=None: HttpsConnection(
            api_url="https://tenant.example.com",
            token="sensitive-token",
            env=explicit_env or "",
        ),
    )
    monkeypatch.setattr(
        config.https_transport,
        "relay_https",
        lambda request, connection: response,
    )

    with pytest.raises(config.DbAdminSetupError):
        config._resolve_control_plane_database(
            "tenant-prod",
            config_path=tmp_path / "custom-config.json",
        )


def _env(
    *,
    project: str = "yoke",
    env_name: str = "stage",
    activation_state: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        project=project,
        env_name=env_name,
        activation_state=activation_state,
        stack_name=f"yoke-{env_name}",
        database_name=f"yoke_{env_name}",
        origin_host=f"origin.{env_name}.example.com",
        ssh_key_path=f"/tmp/yoke-{env_name}.pem",
        ssh_target=f"ubuntu@origin.{env_name}.example.com",
        aws_region="us-east-1",
    )
