"""Shared test PostgreSQL starts only for Yoke source tests."""

from io import StringIO

import pytest

from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_core.domain import db_backend, test_postgres_cluster
from yoke_core.tools import _pytest_parallel, gate_admission, pg_testcluster
from yoke_core.tools import pytest_worker_budget as budget


@pytest.mark.parametrize("ready", [False, True])
def test_maintenance_dsn_only_probes_existing_cluster(monkeypatch, capsys, ready):
    monkeypatch.delenv(db_backend.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.setattr(test_postgres_cluster, "_is_ready", lambda: ready)
    monkeypatch.setattr(
        pg_testcluster, "ensure_started",
        lambda: pytest.fail("admission must not start PostgreSQL"),
    )
    monkeypatch.setattr(test_postgres_cluster, "dsn", lambda: "host=fixture port=1234")

    expected = "host=fixture port=1234 dbname=postgres" if ready else None
    assert gate_admission.maintenance_dsn() == expected
    assert capsys.readouterr().err == ""


def test_maintenance_dsn_preserves_explicit_environment(monkeypatch):
    monkeypatch.setenv(db_backend.PG_DSN_ENV, "host=explicit dbname=tests")
    monkeypatch.setattr(
        db_backend, "resolve_pg_dsn", lambda: "host=explicit dbname=tests",
    )
    monkeypatch.setattr(
        test_postgres_cluster, "_is_ready",
        lambda: pytest.fail("explicit DSN must not probe shared cluster"),
    )
    assert gate_admission.maintenance_dsn() == (
        "host=explicit dbname=tests dbname=postgres"
    )


@pytest.mark.parametrize("source_checkout", [False, True])
def test_auto_workers_prepare_only_tested_yoke_tree(
    monkeypatch, tmp_path, source_checkout,
):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n' if source_checkout
        else '[project]\nname = "external-project"\n',
    )
    if source_checkout:
        (tmp_path / "runtime" / "harness").mkdir(parents=True)
    assert is_yoke_source_checkout(tmp_path) is source_checkout
    monkeypatch.chdir(tmp_path)
    prepared = []
    monkeypatch.setattr(pg_testcluster, "prepare_for_pytest", lambda: prepared.append(True))

    _pytest_parallel.apply_postgres_xdist_auto_env(["-n", "auto"], {})

    assert prepared == ([True] if source_checkout else [])


def test_worker_budget_is_silent_without_cluster(monkeypatch):
    monkeypatch.delenv(budget.HELD_ENV, raising=False)
    monkeypatch.setattr(gate_admission, "maintenance_dsn", lambda: None)
    monkeypatch.setattr(budget, "budget_size", lambda: 4)
    stream = StringIO()

    with budget.granted_workers(
        ["-n", "auto"],
        {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"},
        stream=stream,
    ) as grant:
        assert grant.workers is None

    assert stream.getvalue() == ""
