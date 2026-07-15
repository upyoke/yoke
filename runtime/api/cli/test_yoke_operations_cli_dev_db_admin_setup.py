"""CLI tests for ``yoke dev db-admin setup``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_cli import main as yoke_operations_cli


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
    dsn = (
        "host=stage.cluster.internal port=5432 user=yoke_admin "
        "password=top-secret dbname=yoke_stage"
    )
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
        "_resolve_environment_dsn",
        lambda env, emit=None: (
            dsn,
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
    assert "top-secret" not in captured.out
    assert "top-secret" not in captured.err
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
        "database_name": "yoke_stage",
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
        "_resolve_environment_dsn",
        lambda env, emit=None: (
            "host=prod.cluster.internal port=5432 user=yoke_admin "
            "password=top-secret dbname=yoke_prod",
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
    assert "top-secret" not in captured.out
    assert "top-secret" not in captured.err
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
