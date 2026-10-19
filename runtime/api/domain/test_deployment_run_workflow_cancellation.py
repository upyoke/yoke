"""An ended deployment run cancels the GitHub workflows it dispatched."""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_run_terminalization as terminalization
from yoke_core.domain import deployment_run_workflow_cancellation as cancellation
from yoke_core.domain.github_actions_run_cancel import (
    ALREADY_COMPLETED,
    CANCEL_REQUESTED,
    RunCancelError,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


RUN = "run-20990101-001"
OTHER_RUN = "run-20990101-002"
REPO = "upyoke/yoke"


class _OpenConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        return None


def _slug(test_db) -> str:
    return str(test_db.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0])


def _seed_run(test_db, run_id: str) -> None:
    test_db.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2099-01-01T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    test_db.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages, created_at) "
        "VALUES (%s, 1, %s, '[]', '2099-01-01T00:00:00Z') ON CONFLICT DO NOTHING",
        (f"flow-{run_id}", f"flow-{run_id}"),
    )
    test_db.execute(
        "INSERT INTO deployment_runs (id, project_id, flow, target_tier, "
        "target_environment_id, status, current_stage, created_at) "
        "VALUES (%s, 1, %s, 'persistent', (SELECT id FROM environments "
        "WHERE project_id=1 AND name='prod'), 'executing', 'deploy', "
        "'2099-01-01T00:00:00Z')",
        (run_id, f"flow-{run_id}"),
    )


def _intent(test_db, request_id, attempt, run, *, state="completed", scope=1):
    test_db.execute(
        "INSERT INTO github_workflow_dispatch_intents (request_id, attempt, "
        "actor_id, authorization_scope, payload_checksum, repo, workflow, "
        "workflow_ref, inputs, correlation_id, state, workflow_run_id, "
        "created_at, updated_at) VALUES (%s, %s, '2', %s, 'sum', %s, "
        "'deploy.yml', 'main', '{}', %s, %s, %s, '2099-01-01T00:00:00Z', "
        "'2099-01-01T00:00:00Z')",
        (
            request_id,
            attempt,
            f"project:{scope}",
            REPO,
            f"corr-{request_id}-{attempt}",
            state,
            run,
        ),
    )


@pytest.fixture
def seeded(test_db):
    slug = _slug(test_db)
    _seed_run(test_db, RUN)
    _seed_run(test_db, OTHER_RUN)
    base = f"deploy:{slug}:{RUN}"
    _intent(test_db, f"{base}:stage", 1, "101")
    _intent(test_db, f"{base}:stage", 2, "102")
    _intent(test_db, f"{base}:prod:fresh:abc", 1, "103")
    _intent(test_db, f"{base}:smoke", 1, "", state="pending")
    _intent(test_db, f"{base}:refused", 1, "", state="rejected")
    _intent(test_db, f"deploy:{slug}:{OTHER_RUN}:stage", 1, "999")
    test_db.commit()
    return slug


@pytest.fixture
def github(monkeypatch):
    calls = []
    outcomes = {"103": ALREADY_COMPLETED}

    def _cancel(*, repo, run_id, token):
        calls.append((repo, run_id, token))
        if run_id == "500":
            raise RunCancelError("GitHub refused")
        return outcomes.get(run_id, CANCEL_REQUESTED)

    monkeypatch.setattr(cancellation, "cancel_run", _cancel)
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **_: ProjectGithubAuth(project=project, repo=REPO, token="t"),
    )
    return calls


def test_newest_attempt_of_each_recorded_dispatch_is_cancelled(test_db, seeded, github):
    results = cancellation.cancel_run_workflows(test_db, RUN)

    assert sorted(run for _, run, _ in github) == ["102", "103"]
    by_run = {entry["workflow_run_id"]: entry for entry in results}
    assert by_run["102"]["outcome"] == CANCEL_REQUESTED
    assert by_run["103"]["outcome"] == ALREADY_COMPLETED
    (unidentified,) = [e for e in results if e["outcome"] == "run_unidentified"]
    assert "corr-" in unidentified["detail"]
    assert len(results) == 3


def test_a_refused_cancellation_is_reported_with_its_recovery(
    test_db, seeded, github, caplog
):
    _intent(test_db, f"deploy:{seeded}:{RUN}:late", 1, "500")
    test_db.commit()

    results = cancellation.cancel_run_workflows(test_db, RUN)

    (failed,) = [e for e in results if e["outcome"] == "cancel_failed"]
    assert failed["workflow_run_id"] == "500"
    assert (
        f"yoke github-actions run cancel {REPO} 500 --project {seeded}"
        in (failed["detail"])
    )
    assert "was not cancelled" in caplog.text


def test_a_binding_mismatch_is_reported_not_cancelled(test_db, seeded, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **_: ProjectGithubAuth(
            project=project, repo="someone/else", token="t"
        ),
    )
    monkeypatch.setattr(
        cancellation,
        "cancel_run",
        lambda **_: pytest.fail("a mismatched binding must not be used"),
    )

    results = cancellation.cancel_run_workflows(test_db, RUN)

    assert {e["outcome"] for e in results} == {"cancel_failed", "run_unidentified"}


def test_terminalize_run_returns_the_cancellations(
    test_db, seeded, github, monkeypatch
):
    monkeypatch.setattr(terminalization, "connect", lambda: _OpenConnection(test_db))

    result = terminalization.terminalize_run(
        RUN, disposition="cancelled", reason="stale", actor_id=None, session_id="s"
    )

    assert result.final_status == "cancelled"
    assert {e["workflow_run_id"] for e in result.workflow_cancellations} == {
        "102",
        "103",
        "",
    }


def test_a_failed_status_write_cancels_after_its_commit(test_db, seeded, monkeypatch):
    from yoke_core.domain import deployment_runs_crud_mutate

    cancelled = []
    monkeypatch.setattr(
        cancellation,
        "cancel_run_workflows",
        lambda conn, run_id: cancelled.append(run_id) or [],
    )
    monkeypatch.setattr(
        deployment_runs_crud_mutate, "connect", lambda *_: _OpenConnection(test_db)
    )

    assert deployment_runs_crud_mutate.cmd_update(RUN, "status", "failed") is None
    assert cancelled == [RUN]
    status = test_db.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert status == "failed"


def test_a_rejected_stage_cancels_after_the_resolution_commits(test_db, monkeypatch):
    from yoke_core.domain.deployment_stage_decision_effect import (
        notify_deployment_stage_decision,
    )

    cancelled = []
    monkeypatch.setattr(
        cancellation,
        "cancel_run_workflows",
        lambda conn, run_id: cancelled.append(run_id) or [],
    )
    request = {"subject_key": f"{RUN}:prod", "subject_context": {}}

    assert (
        notify_deployment_stage_decision(test_db, request, action="reject", note=None)
        is None
    )
    assert cancelled == [RUN]


def test_an_unreadable_dispatch_store_leaves_the_connection_usable(test_db):
    class _Broken:
        def __init__(self, conn):
            self._conn = conn
            self.rolled_back = False

        def execute(self, sql, params=()):
            if "github_workflow_dispatch_intents" in sql:
                self._conn.execute("SELECT * FROM table_that_does_not_exist")
            return self._conn.execute(sql, params)

        def rollback(self):
            self.rolled_back = True
            self._conn.rollback()

    _seed_run(test_db, RUN)
    test_db.commit()
    broken = _Broken(test_db)

    (result,) = cancellation.cancel_run_workflows(broken, RUN)

    assert result["outcome"] == "cancel_failed"
    assert broken.rolled_back
    assert test_db.execute("SELECT 1").fetchone()[0] == 1
