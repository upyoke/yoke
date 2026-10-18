"""Local queues survive optional issue publication and reentry."""

import io
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.epic_task_sync_orchestrator_test_support import (
    _mock_yoke_root as _mock_yoke_root,
    _stub_project_github_auth as _stub_project_github_auth,
    _stub_typed_rest_surfaces as _stub_typed_rest_surfaces,
    db as db,
    declare_no_file_tasks,
)
from yoke_core.domain import backlog_github_sync, epic_task_sync
from yoke_core.domain.item_worktrees import record_worker_item_worktree


def _seed(db, mode):
    db.execute(
        "UPDATE projects SET github_sync_mode=%s, public_item_prefix='EXT' WHERE id=2",
        (mode,),
    )
    insert_item(
        db, id=10, workflow_id="epic", status="planned", project="externalwebapp"
    )
    for number, branch, deps in [
        (1, "worker-a", ""),
        (2, "worker-a", "001"),
        (3, "worker-b", "002"),
    ]:
        insert_epic_task(
            db,
            epic_id=10,
            task_num=number,
            title=f"Task {number}",
            status="planned",
            item_worktree_id=record_worker_item_worktree(
                db, item_id=10, branch=branch, path=None
            )["id"],
            dependencies=deps,
        )
    declare_no_file_tasks(db, 10)
    record_worker_item_worktree(
        db, item_id=10, branch="worker-a", path="/tmp/custom-worker-a"
    )
    db.commit()


def _facts(db):
    return [
        tuple(row)
        for row in db.execute(
            "SELECT c.id, c.item_worktree_id, iw.branch, iw.path, c.queue, "
            "c.current_index, c.current_task, c.current_attempt, c.last_updated "
            "FROM epic_dispatch_chains c JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            "WHERE c.epic_id=10 ORDER BY iw.branch"
        ).fetchall()
    ]


@pytest.mark.parametrize("mode", ["enabled", "disabled"])
def test_sync_generates_same_local_queues_and_retry_preserves_identity(db, mode):
    _seed(db, mode)
    out, err = io.StringIO(), io.StringIO()
    with (
        patch("yoke_core.domain.github_rest.create_issue") as remote,
        patch("yoke_core.domain.epic_task_sync_github_create._label_rest.add_labels"),
    ):
        remote.return_value.number = 123
        remote.return_value.html_url = ""
        assert (
            epic_task_sync.sync_epic_tasks(10, conn=db, stdout=out, stderr=err) == 0
        ), err.getvalue()
        before = _facts(db)
        assert [(row[2], row[4], row[6]) for row in before] == [
            ("worker-a", '["001", "002"]', "001"),
            ("worker-b", '["003"]', "003"),
        ]
        assert before[0][3] == "/tmp/custom-worker-a"
        db.execute(
            "UPDATE epic_dispatch_chains SET current_index=1, current_task='002', "
            "current_attempt=2 WHERE id=%s",
            (before[0][0],),
        )
        db.commit()
        before = _facts(db)
        assert epic_task_sync.sync_epic_tasks(10, conn=db, stdout=out, stderr=err) == 0
        assert _facts(db) == before
        assert (
            db.execute("SELECT COUNT(*) FROM epic_tasks WHERE epic_id=10").fetchone()[0]
            == 3
        )
        if mode == "disabled":
            remote.assert_not_called()
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM epic_tasks WHERE epic_id=10 AND github_issue IS NOT NULL"
                ).fetchone()[0]
                == 0
            )


def test_disabled_item_sync_reentry_materializes_chains_without_remote_auth(db):
    _seed(db, "disabled")
    out = io.StringIO()
    with (
        patch(
            "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
            side_effect=AssertionError("remote auth"),
        ),
        patch(
            "yoke_core.domain.epic_task_sync_github_orchestrator.resolve_project_github_auth",
            side_effect=AssertionError("remote auth"),
        ),
        patch(
            "yoke_core.domain.github_rest.create_issue",
            side_effect=AssertionError("remote write"),
        ),
    ):
        assert backlog_github_sync.sync_item(10, conn=db, stdout=out) == 0
        before = _facts(db)
        assert len(before) == 2
        assert backlog_github_sync.sync_item(10, conn=db, stdout=out) == 0
        assert _facts(db) == before


@pytest.mark.parametrize("mode", ["enabled", "disabled"])
def test_implicit_scope_refuses_before_any_chain_or_remote_write(db, mode):
    _seed(db, mode)
    db.execute(
        "UPDATE epic_tasks SET body='Task body without a file list' "
        "WHERE epic_id=10 AND task_num=2"
    )
    db.commit()
    err = io.StringIO()
    with patch("yoke_core.domain.github_rest.create_issue") as remote:
        assert epic_task_sync.sync_epic_tasks(10, conn=db, stderr=err) == 1
        assert "task 2 has no ## Files Touched section" in err.getvalue()
        assert _facts(db) == []
        remote.assert_not_called()


def test_remote_auth_failure_keeps_local_chains_for_retry(db):
    from yoke_core.domain.project_github_auth import ProjectGithubAuthError

    _seed(db, "enabled")
    err = io.StringIO()
    with patch(
        "yoke_core.domain.epic_task_sync_github_orchestrator.resolve_project_github_auth",
        side_effect=ProjectGithubAuthError(
            "externalwebapp", "Restore project authorization"
        ),
    ):
        assert epic_task_sync.sync_epic_tasks(10, conn=db, stderr=err) == 1
    assert len(_facts(db)) == 2
    assert "project_github_auth_error" in err.getvalue()


def test_packaged_server_generates_chains_without_a_checkout(db):
    _seed(db, "disabled")
    with patch(
        "yoke_core.domain.epic_task_sync._repo_root",
        side_effect=AssertionError("API server has no checkout"),
    ):
        assert epic_task_sync.sync_epic_tasks(10, conn=db) == 0
    chains = _facts(db)
    assert len(chains) == 2
    assert chains[0][3] == "/tmp/custom-worker-a"
    assert chains[1][3] is None


def test_inactive_task_lane_refuses_before_generating_queues(db):
    _seed(db, "disabled")
    db.execute(
        "UPDATE item_worktrees SET state='released' WHERE item_id=10 AND branch='worker-b'"
    )
    db.commit()
    err = io.StringIO()
    assert epic_task_sync.sync_epic_tasks(10, conn=db, stderr=err) == 1
    assert _facts(db) == []
    assert "dispatch_lane_missing" in err.getvalue()
    assert "/yoke refine" in err.getvalue()
