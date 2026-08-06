"""Merge-gating execution coverage for this repo's project health checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.migration_yoke_ledger import governed_yoke_postgres_seed
from yoke_core.engines.doctor_applicability import (
    DoctorContext,
    RUNTIME_LOCAL,
    not_applicable_reason,
)
from yoke_core.engines.doctor_project_checks import (
    discover_project_checks,
    project_checks_dir,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


REPO_ROOT = Path(__file__).resolve().parents[3]


def _discovery(checkout: Path = REPO_ROOT):
    discovery = discover_project_checks(checkout)
    assert not discovery.failures, [
        (failure.path.name, failure.error) for failure in discovery.failures
    ]
    return discovery


def _local_context(*, source_checkout: Path | None) -> DoctorContext:
    return DoctorContext(
        project="yoke",
        runtime=RUNTIME_LOCAL,
        self_project="yoke",
        source_checkout=source_checkout,
    )


def _run_checks(checks, conn) -> None:
    args = DoctorArgs(project="yoke", quick=True)
    for check in checks:
        recorder = RecordCollector()
        if conn is None:
            check.fn(conn, args, recorder)
            continue
        conn.execute("SAVEPOINT project_check_execution")
        try:
            check.fn(conn, args, recorder)
        finally:
            conn.execute("ROLLBACK TO SAVEPOINT project_check_execution")
            conn.execute("RELEASE SAVEPOINT project_check_execution")


def _seed_migration_model(conn) -> None:
    settings = governed_yoke_postgres_seed({"environment_id": "test"})
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (%s, %s, %s) "
        "ON CONFLICT(project_id, type) DO UPDATE SET settings = excluded.settings",
        (1, "migration_model", json.dumps(settings)),
    )
    conn.commit()


def test_every_project_check_imports_and_executes(test_db) -> None:
    """Function-local imports run against the disposable control plane."""
    discovery = _discovery()
    _seed_migration_model(test_db)

    local_context = _local_context(source_checkout=REPO_ROOT)
    for check in discovery.checks:
        assert not_applicable_reason(check.applicability, local_context) is None

    _run_checks(discovery.checks, test_db)


def test_project_checks_declare_their_source_checkout_requirement() -> None:
    """A runner without this source tree reports N/A instead of skipping."""
    no_checkout = _local_context(source_checkout=None)
    for check in _discovery().checks:
        reason = not_applicable_reason(check.applicability, no_checkout)
        assert reason is not None, check.slug
        assert "source tree" in reason, check.slug


def test_function_body_symbol_failure_is_executable_coverage(
    tmp_path: Path,
) -> None:
    """Discovery alone stays green; executing the body exposes the defect."""
    folder = project_checks_dir(tmp_path)
    folder.mkdir(parents=True)
    (folder / "check_function_body_symbol.py").write_text(
        "import json\n\n"
        "def hc_function_body_symbol(conn, args, rec):\n"
        "    json.symbol_that_does_not_exist('{}')\n",
        encoding="utf-8",
    )

    discovery = _discovery(tmp_path)
    assert len(discovery.checks) == 1
    with pytest.raises(AttributeError, match="symbol_that_does_not_exist"):
        _run_checks(discovery.checks, None)
