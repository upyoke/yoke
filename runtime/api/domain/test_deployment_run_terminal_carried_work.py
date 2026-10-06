"""Terminal runs record carried work once, so no read derives it again."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain import (
    deployment_run_carried_work_read,
    deployment_run_carried_work_source,
    deployment_runs,
)
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.deployment_run_list_read import list_deployment_runs
from yoke_core.domain.deployment_run_terminalization import terminalize_run


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "main", str(repo))
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("next\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Routine maintenance")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _run(conn: Any, run_id: str, lineage: str, status: str, created_at: str) -> None:
    completed_at = created_at if status == "succeeded" else None
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "completed_at) VALUES (%s,1,'terminal-carried-flow',%s,%s,'complete',%s,%s)",
        (run_id, lineage, status, created_at, completed_at),
    )
    conn.commit()


@pytest.fixture
def opened(test_db: Any, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """A succeeded baseline plus a counted source opener."""
    repo, base, head = _repository(tmp_path)
    test_db.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at,status) "
        "VALUES ('terminal-carried-flow',1,'Terminal carried','',"
        "'[{\"name\":\"complete\"}]','2026-08-30T00:00:00Z','active')"
    )
    _run(test_db, "run-terminal-000", base, "succeeded", "2026-08-30T00:01:00Z")
    state: dict[str, Any] = {"opens": 0, "checkout": repo, "head": head}

    def checkout(_project_id: int) -> Path:
        state["opens"] += 1
        return state["checkout"]

    monkeypatch.setattr(
        deployment_run_carried_work_source, "checkout_for_project_id", checkout
    )
    deployment_run_carried_work_read._CACHE.clear()
    return state


def _stored(conn: Any, run_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    return parse_carried_work(row["carried_work"])


@pytest.mark.parametrize("final_status", ["failed", "cancelled"])
def test_unsuccessful_completion_records_carried_work(
    test_db: Any, opened: dict[str, Any], final_status: str
) -> None:
    _run(
        test_db, "run-terminal-001", opened["head"], "executing", "2026-08-30T00:02:00Z"
    )

    assert (
        deployment_runs.cmd_update("run-terminal-001", "status", final_status) is None
    )

    carried = _stored(test_db, "run-terminal-001")
    assert carried is not None
    assert carried["commits"] == [opened["head"]]


def test_operator_terminalization_records_carried_work(
    test_db: Any, opened: dict[str, Any]
) -> None:
    _run(test_db, "run-terminal-002", opened["head"], "created", "2026-08-30T00:02:00Z")

    terminalize_run(
        "run-terminal-002",
        disposition="cancelled",
        reason="superseded",
        actor_id=None,
        session_id="",
    )

    carried = _stored(test_db, "run-terminal-002")
    assert carried is not None
    assert carried["commits"] == [opened["head"]]


def test_unsaved_terminal_run_is_derived_once_then_read_from_its_record(
    test_db: Any, opened: dict[str, Any]
) -> None:
    _run(test_db, "run-terminal-003", opened["head"], "failed", "2026-08-30T00:02:00Z")

    first = list_deployment_runs(project=None, status="failed", limit=10)
    assert opened["opens"] == 1
    second = list_deployment_runs(project=None, status="failed", limit=10)

    assert opened["opens"] == 1
    assert first[0]["carried_work"]["commits"] == [opened["head"]]
    assert second[0]["carried_work"] == first[0]["carried_work"]
    assert _stored(test_db, "run-terminal-003") == first[0]["carried_work"]


def test_failed_derivation_of_a_terminal_run_is_recorded_and_not_retried(
    test_db: Any, opened: dict[str, Any], tmp_path: Path
) -> None:
    opened["checkout"] = tmp_path / "missing-checkout"
    _run(
        test_db, "run-terminal-004", opened["head"], "cancelled", "2026-08-30T00:02:00Z"
    )

    first = list_deployment_runs(project=None, status="cancelled", limit=10)
    second = list_deployment_runs(project=None, status="cancelled", limit=10)

    assert opened["opens"] == 1
    derivation = first[0]["carried_work"]["derivation"]
    assert derivation["contents_known"] is False
    assert derivation["reason"]
    assert second[0]["carried_work"] == first[0]["carried_work"]
    stored = _stored(test_db, "run-terminal-004")
    assert stored is not None and stored["derivation"]["reason"] == derivation["reason"]
