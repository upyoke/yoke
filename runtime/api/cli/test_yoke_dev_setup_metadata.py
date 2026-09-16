"""Disposable Postgres and authority metadata for ``yoke dev setup``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import source_checkout_activation


@pytest.fixture(autouse=True)
def _stub_source_link(monkeypatch):
    monkeypatch.setattr(
        source_checkout_activation,
        "_run_source_link_subprocess",
        lambda root, **_kwargs: {
            "mode": "source-link",
            "warnings": [],
            "machine_config_newly_registered": False,
        },
    )


def _source_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "yoke-source"
    (checkout / "runtime" / "harness").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8"
    )
    return checkout


def test_dev_setup_dry_run_plans_disposable_postgres(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = _source_checkout(tmp_path)
    rc = yoke_operations_cli.main(
        ["dev", "setup", str(checkout), "--with-test-postgres", "--dry-run", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "start-disposable-postgres" in [
        step["action"] for step in payload["plan"]["steps"]
    ]
    assert payload["plan"]["credential_source"]["path"].endswith("source-dev-admin.dsn")


def test_dev_setup_apply_writes_tunnel_and_authority_metadata(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    checkout = _source_checkout(tmp_path)
    config = machine_home / "config.json"
    rc = yoke_operations_cli.main(
        [
            "dev", "setup", str(checkout), "--dsn",
            "host=/tmp user=yoke dbname=postgres", "--config", str(config),
            "--postgres-host", "127.0.0.1", "--postgres-port", "6547",
            "--tunnel-bastion", "ubuntu@example.invalid",
            "--tunnel-identity-file", "~/.ssh/yoke.pem",
            "--tunnel-remote-host", "db.internal", "--tunnel-remote-port", "5432",
            "--authority-kind", "aws_aurora_postgres",
            "--authority-infra-dir", "infra/pulumi/yoke-cloud",
            "--authority-stack", "yoke-prod", "--authority-region", "us-east-1",
            "--authority-database-name", "yoke_prod", "--yes", "--json",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    entry = json.loads(config.read_text(encoding="utf-8"))["connections"][
        "source-dev-admin"
    ]
    assert entry["prod"] is False
    assert entry["postgres"] == {
        "host": "127.0.0.1", "port": 6547,
        "tunnel": {
            "kind": "ssh", "bastion": "ubuntu@example.invalid",
            "identity_file": "~/.ssh/yoke.pem", "remote_host": "db.internal",
            "remote_port": 5432,
        },
    }
    assert entry["authority"] == {
        "kind": "aws_aurora_postgres", "infra_dir": "infra/pulumi/yoke-cloud",
        "location": {
            "stack": "yoke-prod", "region": "us-east-1",
            "database_name": "yoke_prod",
        },
    }
