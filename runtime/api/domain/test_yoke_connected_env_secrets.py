"""Declared AWS secret sources for machine connections."""

from runtime.api.fixtures.machine_config_test import select_machine_config_file
import json
from pathlib import Path
import pytest
from yoke_core.domain import db_backend, yoke_connected_env
from runtime.api.domain.yoke_connected_env_test_support import _clean_env


def test_aws_secret_source_uses_declared_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import subprocess

    from yoke_core.domain import deploy_remote, yoke_cloud_db_authority

    _clean_env(monkeypatch)
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_PROFILE", "operator-ambient-login")
    repo = tmp_path / "repo"
    binding = repo / ".yoke" / "config.json"
    binding.parent.mkdir(parents=True)
    binding.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "authority": {
                            "kind": "aws_aurora_postgres",
                            "infra_dir": "projects/yoke/infra",
                            "location": {
                                "stack": "yoke-prod",
                                "region": "us-east-1",
                                "database_name": "yoke_prod",
                            },
                        },
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                        "credential_source": {
                            "kind": "aws_secrets_manager",
                            "project": "yoke",
                        },
                    },
                },
                "connection_projects": {
                    "prod-db-admin": [
                        {"checkout": str(repo.resolve()), "project_id": 1}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    select_machine_config_file(monkeypatch, binding)
    monkeypatch.setattr(
        deploy_remote.capability_machine_secrets,
        "read_machine_capability_secret",
        lambda project, cap_type, key: {
            "access_key_id": "AKIACAPABILITY",
            "secret_access_key": "capability-secret",
        }.get(key),
    )
    children: list[tuple[list[str], str | None, dict]] = []

    def fake_run(argv, *, cwd=None, env=None, **_kwargs):
        children.append((argv, cwd, env))
        stdout = (
            json.dumps(
                {
                    "databaseClusterEndpoint": "db.internal",
                    "databaseSecretArn": "arn:secret",
                }
            )
            if argv[0] == "pulumi"
            else json.dumps({"username": "admin", "password": "secret"})
        )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(yoke_cloud_db_authority.subprocess, "run", fake_run)

    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

    assert [argv[:2] for argv, _cwd, _env in children] == [
        ["pulumi", "stack"],
        ["aws", "secretsmanager"],
    ]
    assert children[0][1] == str(repo / "projects/yoke/infra")
    for _argv, _cwd, env in children:
        assert env["AWS_ACCESS_KEY_ID"] == "AKIACAPABILITY"
        assert env["AWS_SECRET_ACCESS_KEY"] == "capability-secret"
        assert env["AWS_CONFIG_FILE"] == os.devnull
        assert env["AWS_SHARED_CREDENTIALS_FILE"] == os.devnull
        assert "AWS_PROFILE" not in env
    assert resolved.process_env == {
        db_backend.PG_DSN_ENV: (
            "host=127.0.0.1 port=6547 user=admin password=secret dbname=yoke_prod"
        )
    }
    assert resolved.evidence["connection"] == {"host": "127.0.0.1", "port": 6547}
    assert "secret" not in resolved.redacted_dsn


def test_direct_aws_secret_source_refreshes_without_database_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_core.domain import cloud_db_secret_dsn, deploy_remote
    from yoke_core.domain import yoke_cloud_db_authority

    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = repo / ".yoke" / "config.json"
    binding.parent.mkdir(parents=True)
    binding.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "authority": {
                            "kind": "aws_aurora_postgres",
                            "location": {
                                "stack": "yoke-prod",
                                "region": "us-east-1",
                                "database_name": "yoke_prod",
                            },
                        },
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                        "credential_source": {
                            "kind": "aws_secrets_manager",
                            "secret_arn": "arn:aws:secretsmanager:example",
                            "region": "us-east-1",
                            "project": "yoke",
                        },
                    },
                },
                "connection_projects": {
                    "prod-db-admin": [
                        {"checkout": str(repo.resolve()), "project_id": 1}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    select_machine_config_file(monkeypatch, binding)
    monkeypatch.setattr(
        deploy_remote,
        "aws_machine_capability_env",
        lambda project, region: {
            "AWS_ACCESS_KEY_ID": f"{project}-access",
            "AWS_SECRET_ACCESS_KEY": f"{region}-secret",
        },
    )
    loads = []

    def fake_load(
        secret_arn,
        *,
        region=None,
        env=None,
        version_stage=None,
    ):
        loads.append((secret_arn, region, dict(env or {}), version_stage))
        password = "previous-password" if version_stage else "current-password"
        return json.dumps(
            {"username": "yoke_admin", "password": password, "port": 5432}
        )

    monkeypatch.setattr(yoke_cloud_db_authority, "load_secret_string", fake_load)
    cloud_db_secret_dsn.clear_cache()

    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )
    previous = yoke_connected_env.resolve_previous_postgres_dsn()

    assert "password=current-password" in resolved.dsn
    assert "password=previous-password" in previous
    assert resolved.process_env == {db_backend.PG_DSN_ENV: resolved.dsn}
    assert "current-password" not in resolved.redacted_dsn
    assert [call[3] for call in loads] == [None, "AWSPREVIOUS"]
    assert all(call[2]["AWS_ACCESS_KEY_ID"] == "yoke-access" for call in loads)
    cloud_db_secret_dsn.clear_cache()
