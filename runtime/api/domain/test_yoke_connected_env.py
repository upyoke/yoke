from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from yoke_core.cli import raw_query
from yoke_core.domain import db_backend, machine_config, yoke_connected_env
from yoke_core.domain import db_helpers


def _binding(root: Path, dsn_file: Path, *, prod: bool | None = None) -> Path:
    path = root / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = {
        "transport": "local-postgres",
        "authority": {
            "kind": "aws_aurora_postgres",
            "infra_dir": "projects/example/infra",
            "location": {
                "stack": "example-prod",
                "database_name": "example_prod",
            },
        },
        "credential_source": {
            "kind": "dsn_file",
            "path": str(dsn_file),
        },
    }
    if prod is not None:
        connection["prod"] = prod
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": connection,
                },
                "projects": {str(root.resolve()): {"project_id": 7}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        db_backend.PG_DSN_ENV,
        db_backend.PG_DSN_FILE_ENV,
        "YOKE_DB",
        machine_config.CONFIG_FILE_ENV,
        yoke_connected_env.DISABLE_ENV,
        yoke_connected_env.PYTEST_ENABLE_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")


def test_walks_parent_dirs_and_resolves_dsn_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "outside-repo.dsn"
    dsn_file.write_text(
        "host=127.0.0.1 user=admin password=secret dbname=example\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    child = repo / "a" / "b"
    child.mkdir(parents=True)
    monkeypatch.chdir(child)

    active = yoke_connected_env.load_active()
    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

    assert active is not None
    assert active.project == "7"
    assert active.project_id == 7
    assert active.backend == db_backend.POSTGRES
    assert resolved.dsn.startswith("host=127.0.0.1")
    assert "secret" not in resolved.redacted_dsn
    assert resolved.process_env == {db_backend.PG_DSN_FILE_ENV: str(dsn_file)}


def test_explicit_env_and_fixture_db_override_connected_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.chdir(repo)

    assert db_backend.is_postgres()

    monkeypatch.setenv("YOKE_DB", str(tmp_path / "fixture.db"))
    assert db_backend.is_postgres()


def test_resolve_postgres_dsn_allows_explicit_prod_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "prod.dsn"
    dsn_file.write_text("host=prod dbname=yoke_prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file, prod=True)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.chdir(repo)

    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

    assert resolved.dsn == "host=prod dbname=yoke_prod"
    assert resolved.process_env == {db_backend.PG_DSN_FILE_ENV: str(dsn_file)}


def test_explicit_pg_dsn_env_bypasses_prod_flagged_machine_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = _binding(repo, tmp_path / "missing.dsn", prod=True)
    explicit = "host=operator dbname=yoke_prod"
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(db_backend.PG_DSN_ENV, explicit)
    monkeypatch.chdir(repo)

    assert db_backend.resolve_pg_dsn() == explicit


def test_raw_query_surfaces_missing_prod_admin_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = _binding(repo, tmp_path / "missing.dsn", prod=True)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.chdir(repo)

    err = StringIO()

    assert raw_query.execute_query("SELECT 1", err=err) == 1
    assert "missing" in err.getvalue()
    assert "prod-flagged" not in err.getvalue()


def test_retired_canonical_yoke_db_does_not_override_connected_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    canonical = repo / "data" / "yoke.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("YOKE_DB", str(canonical))

    assert db_backend.is_postgres()
    reason = yoke_connected_env.retired_db_guard_reason()
    assert "retired local SQLite authority" in str(reason)
    with pytest.raises(RuntimeError, match="SQLite authority retired/guarded"):
        db_helpers.resolve_db_path()


def test_retired_yoke_db_resolves_postgres_from_outside_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    canonical = repo / "data" / "yoke.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.setenv("YOKE_DB", str(canonical))

    assert db_backend.is_postgres()


def test_missing_credential_file_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = _binding(repo, tmp_path / "missing.dsn")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.chdir(repo)

    with pytest.raises(yoke_connected_env.ConnectedEnvError, match="missing"):
        yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )


def test_pytest_ambient_discovery_is_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    monkeypatch.delenv(yoke_connected_env.PYTEST_ENABLE_ENV, raising=False)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.chdir(repo)

    assert yoke_connected_env.find_binding() is None
    assert yoke_connected_env.find_binding(repo) == binding
    assert db_backend.is_postgres()


def test_process_env_overrides_forward_dsn_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.chdir(repo)

    assert yoke_connected_env.process_env_overrides(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    ) == {
        db_backend.PG_DSN_FILE_ENV: str(dsn_file),
    }


def test_aws_secret_source_uses_declared_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
                            "infra_dir": "projects/yoke/infra",
                            "location": {
                                "stack": "yoke-prod",
                                "region": "us-east-1",
                                "database_name": "yoke_prod",
                            },
                        },
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                        "credential_source": {"kind": "aws_secrets_manager"},
                    },
                },
                "projects": {str(repo.resolve()): {"project_id": 1}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))

    def fake_resolve_declared_dsn(
        *, infra_dir, location, host_override=None, port_override=None
    ):
        assert infra_dir == repo / "projects/yoke/infra"
        assert location.stack == "yoke-prod"
        assert location.region == "us-east-1"
        assert host_override == "127.0.0.1"
        assert port_override == 6547
        return (
            "host=127.0.0.1 port=6547 user=admin password=secret dbname=yoke_prod",
            {
                "dsn": (
                    "host=127.0.0.1 port=6547 user=admin "
                    "password=<redacted> dbname=yoke_prod"
                )
            },
        )

    monkeypatch.setattr(
        "yoke_core.domain.yoke_cloud_db_authority.resolve_declared_dsn",
        fake_resolve_declared_dsn,
    )

    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

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
                "projects": {str(repo.resolve()): {"project_id": 1}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
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
