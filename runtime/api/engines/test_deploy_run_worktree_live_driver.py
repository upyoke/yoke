"""A run with a live driver keeps its pinned tree, whatever its status reads.

A re-driven terminal run still reads ``failed`` while its driver freezes
source, so status alone would let a sibling driver's start-up retirement or
the relay lane sweep remove the tree under it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.engines.test_deploy_run_worktree_retirement import (
    _driver_worktree,
    _repo,
    _run_git,
)
from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain import deploy_pipeline_pinned_source as pinned
from yoke_core.domain.handlers.deployment_run_get import handle_deployment_run_get
from yoke_core.engines import deploy_run_worktree_retirement as retirement
from yoke_core.engines.deploy_run_worktree_retirement import (
    LANE_RETIRED,
    LANE_RUN_OPEN,
    retire_terminal_deploy_run_worktrees,
)

RUN = "run-20261117-004"


def _attachment(age: timedelta) -> dict[str, object]:
    beat = format_instant(utc_now() - age)
    return {
        "run_id": RUN,
        "session_id": "driver-session",
        "pid": 4242,
        "attached_at": beat,
        "heartbeat_at": beat,
        "phase": "freezing_source",
        "progress_capture": "",
        "machine_id": "machine-a",
    }


@pytest.fixture
def record(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    row: dict[str, object] = {"status": "failed"}
    monkeypatch.setattr(retirement, "_run_record", lambda _run_id: (dict(row), ""))
    return row


def test_relay_sweep_keeps_a_failed_run_with_a_live_driver(
    tmp_path: Path, record: dict[str, object]
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, RUN)
    record["driver_attachment"] = _attachment(timedelta(seconds=5))

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_RUN_OPEN]
    assert "live driver" in verdicts[0].reason
    assert "freezing_source" in verdicts[0].reason
    assert path.is_dir()


def test_start_up_retirement_keeps_a_sibling_run_with_a_live_driver(
    tmp_path: Path, record: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, RUN)
    record["driver_attachment"] = _attachment(timedelta(seconds=5))

    pinned.retire_finished_driver_worktrees(repo, "run-20261117-006")

    assert path.is_dir()
    assert "Retired" not in capsys.readouterr().out


def test_a_terminal_run_with_a_lapsed_driver_is_still_retired(
    tmp_path: Path, record: dict[str, object]
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, RUN)
    record["driver_attachment"] = _attachment(timedelta(hours=1))

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_RETIRED]
    assert not path.exists()


def test_a_terminal_run_with_no_driver_is_still_retired(
    tmp_path: Path, record: dict[str, object]
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, RUN)
    record["driver_attachment"] = None

    pinned.retire_finished_driver_worktrees(repo, "run-20261117-006")

    assert not path.exists()


def test_run_get_serves_the_recorded_driver_attachment(test_db) -> None:
    import json

    insert_deployment_run(
        test_db,
        id=RUN,
        status="failed",
        driver_attachment=json.dumps(_attachment(timedelta(seconds=5))),
    )
    test_db.commit()

    outcome = handle_deployment_run_get(
        deployment_request(
            function="deployment_runs.get",
            target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
            payload={"fields": ["status", "driver_attachment"]},
        )
    )

    assert outcome.primary_success, outcome.error
    run = outcome.result_payload["run"]
    assert run["status"] == "failed"
    assert run["driver_attachment"]["phase"] == "freezing_source"
    assert run["driver_attachment"]["session_id"] == "driver-session"
