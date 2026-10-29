from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from yoke_core.cli import raw_query
from yoke_core.domain import db_backend, yoke_connected_env
from yoke_core.domain import db_helpers


from runtime.api.domain.yoke_connected_env_test_support import (
    _binding,
    _clean_env,
)

from runtime.api.fixtures.machine_config_test import select_machine_config_file


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
    select_machine_config_file(monkeypatch, str(binding))
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
    select_machine_config_file(monkeypatch, str(binding))
    monkeypatch.chdir(repo)

    assert db_backend.is_postgres()

    monkeypatch.setenv("YOKE_DB", str(tmp_path / "fixture.db"))
    assert db_backend.is_postgres()


def test_resolve_postgres_dsn_allows_explicit_protected_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "prod.dsn"
    dsn_file.write_text("host=prod dbname=yoke_prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file, protected=True)
    select_machine_config_file(monkeypatch, str(binding))
    monkeypatch.chdir(repo)

    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

    assert resolved.dsn == "host=prod dbname=yoke_prod"
    assert resolved.process_env == {db_backend.PG_DSN_FILE_ENV: str(dsn_file)}


def test_explicit_pg_dsn_env_bypasses_protected_flagged_machine_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = _binding(repo, tmp_path / "missing.dsn", protected=True)
    explicit = "host=operator dbname=yoke_prod"
    select_machine_config_file(monkeypatch, str(binding))
    monkeypatch.setenv(db_backend.PG_DSN_ENV, explicit)
    monkeypatch.chdir(repo)

    assert db_backend.resolve_pg_dsn() == explicit


def test_raw_query_surfaces_missing_prod_admin_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = _binding(repo, tmp_path / "missing.dsn", protected=True)
    select_machine_config_file(monkeypatch, str(binding))
    monkeypatch.chdir(repo)

    err = StringIO()

    assert raw_query.execute_query("SELECT 1", err=err) == 1
    assert "missing" in err.getvalue()
    assert "protected" not in err.getvalue()


def test_retired_canonical_yoke_db_does_not_override_connected_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    select_machine_config_file(monkeypatch, str(binding))
    canonical = repo / "data" / "yoke.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("YOKE_DB", str(canonical))

    assert db_backend.is_postgres()
    reason = yoke_connected_env.retired_db_guard_reason()
    assert "retired local SQLite authority" in str(reason)
    assert not hasattr(db_helpers, "resolve" + "_db_path")


def test_retired_yoke_db_resolves_postgres_from_outside_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=target dbname=prod\n", encoding="utf-8")
    repo = tmp_path / "repo"
    binding = _binding(repo, dsn_file)
    select_machine_config_file(monkeypatch, str(binding))
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
    select_machine_config_file(monkeypatch, str(binding))
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
    select_machine_config_file(monkeypatch, str(binding))
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
    select_machine_config_file(monkeypatch, str(binding))
    monkeypatch.chdir(repo)

    assert yoke_connected_env.process_env_overrides(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    ) == {
        db_backend.PG_DSN_FILE_ENV: str(dsn_file),
    }
