"""Repairing a carried-work record whose comparison never ran.

Carried work is written once and then frozen, which is right for an answer
that was computed and wrong for one that only recorded that nobody could
compute it. This repair replaces exactly that record, and only when a fresh
derivation can answer it now.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deployment_run_carried_work_source
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.handlers import (
    deployment_run_carried_work_repair as repair_module,
)
from yoke_core.domain.handlers.deployment_run_carried_work_repair import (
    handle_deployment_run_carried_work_repair,
)
from yoke_core.domain.json_helper import dumps_compact

UNKNOWN_RECORD = {
    "schema": 1,
    "derivation": {
        "status": "unknown",
        "contents_known": False,
        "source": "none",
        "reason": "project_source_unavailable",
        "recovery": "Register a checkout or repair the binding.",
        "run_id": "run-repair-candidate",
    },
    "items": [],
    "commits": [],
    "warnings": [],
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repair-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("landed\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land routine maintenance")
    tip = _git(repo, "rev-parse", "HEAD")
    return repo, baseline, tip


@pytest.fixture
def repair_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        from yoke_core.domain.deployment_runs_schema import cmd_init

        cmd_init(db_path)
        yield db_path


def _seed(db_path: str, *, baseline: str, tip: str, stored: Any) -> None:
    conn = connect_test_db(db_path)
    try:
        insert_deployment_run(
            conn,
            id="run-repair-previous",
            flow="repair-flow",
            status="succeeded",
            release_lineage=baseline,
            completed_at="2026-09-14T01:00:00Z",
        )
        insert_deployment_run(
            conn,
            id="run-repair-candidate",
            flow="repair-flow",
            status="succeeded",
            release_lineage=tip,
            completed_at="2026-09-14T02:00:00Z",
            carried_work=None if stored is None else dumps_compact(stored),
        )
        conn.commit()
    finally:
        conn.close()


def _repair():
    return handle_deployment_run_carried_work_repair(
        _request(
            function="deployment_runs.carried_work.repair",
            target=TargetRef(
                kind="workflow_run", workflow_run_id="run-repair-candidate"
            ),
        )
    )


def _stored(db_path: str) -> dict:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            "SELECT carried_work FROM deployment_runs WHERE id='run-repair-candidate'"
        ).fetchone()
    finally:
        conn.close()
    return parse_carried_work(row[0]) or {}


def test_an_unanswered_record_is_replaced_once_the_comparison_can_run(
    repair_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, baseline, tip = _repository(tmp_path)
    _seed(repair_db_path, baseline=baseline, tip=tip, stored=UNKNOWN_RECORD)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    outcome = _repair()

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["previous_reason"] == "project_source_unavailable"
    derivation = outcome.result_payload["carried_work"]["derivation"]
    assert derivation["contents_known"] is True
    assert derivation["source"] == "checkout"
    assert _stored(repair_db_path)["derivation"]["contents_known"] is True


def test_a_derived_record_is_never_rewritten(
    repair_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Repair replaces a comparison that never ran, not one that did."""
    repo, baseline, tip = _repository(tmp_path)
    derived = {
        "schema": 1,
        "derivation": {
            "status": "derived",
            "contents_known": True,
            "source": "checkout",
            "reason": "complete",
            "run_id": "run-repair-candidate",
        },
        "items": [],
        "commits": ["abc"],
        "warnings": [],
    }
    _seed(repair_db_path, baseline=baseline, tip=tip, stored=derived)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    outcome = _repair()

    assert outcome.primary_success is False
    assert outcome.error.code == "carried_work_already_known"
    assert _stored(repair_db_path)["commits"] == ["abc"]


def test_a_second_unanswerable_derivation_is_refused_rather_than_stored(
    repair_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Reporting success for an answer still nobody has is the defect."""
    _seed(repair_db_path, baseline="a" * 40, tip="b" * 40, stored=UNKNOWN_RECORD)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: None,
    )

    outcome = _repair()

    assert outcome.primary_success is False
    assert outcome.error.code == "carried_work_still_unknown"
    assert "project_source_unavailable" in outcome.error.message
    assert _stored(repair_db_path)["derivation"]["reason"] == (
        "project_source_unavailable"
    )


def test_a_run_with_no_record_is_told_where_one_comes_from(
    repair_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, baseline, tip = _repository(tmp_path)
    _seed(repair_db_path, baseline=baseline, tip=tip, stored=None)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    outcome = _repair()

    assert outcome.primary_success is False
    assert outcome.error.code == "carried_work_absent"


def test_an_unknown_run_is_not_found(repair_db_path: str):
    outcome = handle_deployment_run_carried_work_repair(
        _request(
            function="deployment_runs.carried_work.repair",
            target=TargetRef(kind="workflow_run", workflow_run_id="run-missing"),
        )
    )

    assert outcome.primary_success is False
    assert outcome.error.code == "not_found"


def test_a_record_that_changed_under_the_repair_is_reported_not_overwritten(
    repair_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The write is conditional on the record this call actually read.

    Deriving takes as long as a repository read, and the run stays writable
    through it. On Postgres the row lock keeps another connection out of that
    window; the conditional write is the backend-independent backstop, and it
    is what this drives — the stored record is changed underneath the repair,
    so the update matches nothing and the answer already there survives.
    """
    repo, baseline, tip = _repository(tmp_path)
    _seed(repair_db_path, baseline=baseline, tip=tip, stored=UNKNOWN_RECORD)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    landed_first = {
        "schema": 1,
        "derivation": {
            "status": "derived",
            "contents_known": True,
            "source": "repository_provider",
            "reason": "complete",
            "run_id": "run-repair-candidate",
        },
        "items": [],
        "commits": ["landed-first"],
        "warnings": [],
    }
    real_derive = repair_module.derive_carried_work_safely

    def derive_then_change_the_record(conn, run_id):
        payload = real_derive(conn, run_id)
        conn.execute(
            "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
            (dumps_compact(landed_first), run_id),
        )
        return payload

    monkeypatch.setattr(
        repair_module, "derive_carried_work_safely", derive_then_change_the_record
    )

    outcome = _repair()

    assert outcome.primary_success is False
    assert outcome.error.code == "carried_work_changed_during_repair"
