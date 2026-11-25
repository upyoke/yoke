"""External task commits bind the candidate consumed by review insertion."""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

from runtime.api.conftest import insert_epic_task
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from yoke_cli.commands.adapters import epic_review
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, FunctionCallResponse
from yoke_core.domain.handlers import project_snapshot_sync
from yoke_core.domain import epic, lane_head_client
from yoke_core.domain.item_worktrees import record_item_worktree


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_external_task_commit_records_head_and_accepts_review(
    tmp_path, test_db, monkeypatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "--allow-empty", "-qm", "seed")
    lane = tmp_path / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(lane))
    assert not (repo / ".git/hooks/post-commit").exists()
    item_id = 4254
    insert_item(test_db, id=item_id, workflow_id="epic", project="external")
    lane_row = record_item_worktree(
        test_db, item_id=item_id, branch="task", path=str(lane.resolve()),
        lane_role="worker",
    )
    lane_id = lane_row["id"]
    insert_epic_task(test_db, epic_id=item_id, task_num=1, title="Task")
    test_db.execute(
        "UPDATE epic_tasks SET item_worktree_id=%s WHERE epic_id=%s AND task_num=1",
        (lane_id, item_id),
    )
    requirement = insert_qa_requirement(
        test_db, item_id=None, epic_id=item_id, task_num=1,
        qa_kind="implementation_review",
        success_policy='{"type":"deterministic","criteria":"verdict_pass"}',
    )
    test_db.commit()
    borrowed = MagicMock(wraps=test_db, spec=type(test_db))
    borrowed.__enter__.return_value = test_db
    borrowed.close.return_value = None
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda **kw: borrowed)
    monkeypatch.setattr("yoke_core.domain.qa_execution.connect", lambda **kw: borrowed)

    def dispatch(**kwargs):
        outcome = project_snapshot_sync.handle_project_snapshot_sync(
            FunctionCallRequest(
                function=kwargs["function_id"],
                actor=ActorContext(session_id="test-session"),
                target=kwargs["target"],
                payload=kwargs["payload"],
            )
        )
        return FunctionCallResponse(
            success=outcome.primary_success,
            function=kwargs["function_id"],
            version="v1",
            result=outcome.result_payload or {},
            error=outcome.error,
        )


    reads = {
        "workflow_item.epic_task.get": {"worktree_id": lane_id},
        "items.detail.get": {"item": {"project": {"slug": "external"}, "worktrees": [lane_row]}},
    }

    def review(**call):
        payload = call["payload"]
        result = epic.review_insert(
            test_db, str(item_id), 1, "PASS", payload["body"], head_sha=payload["head_sha"]
        )
        assert "verdict=PASS" in result
        return 0

    monkeypatch.setattr(lane_head_client, "get_structured_dispatch", lambda: SimpleNamespace(
        build_actor=ActorContext,
        call_dispatcher=lambda **call: SimpleNamespace(success=True, result=reads[call["function_id"]]),
    ))
    monkeypatch.setattr(epic_review, "dispatch_and_emit", review)
    adapter = "yoke_cli.commands.adapters.project_snapshot"
    monkeypatch.setattr(f"{adapter}.call_dispatcher", dispatch)
    monkeypatch.setattr(f"{adapter}.ensure_handlers_loaded", lambda: None)
    _git(lane, "commit", "--allow-empty", "-qm", "task change")
    head = _git(lane, "rev-parse", "HEAD")
    monkeypatch.chdir(lane)
    assert epic_review.epic_task_review_insert([
        "--epic", "EXT-4254", "--task-num", "1", "--verdict", "pass",
        "--body", "Reviewed", "--head-sha", head, "--session-id", "test-session",
    ]) == 0

    assert test_db.execute(
        "SELECT commit_sha FROM item_worktrees WHERE id=%s", (lane_id,),
    ).fetchone()[0] == head

    run = test_db.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE qa_requirement_id=%s",
        (requirement["id"],),
    ).fetchone()
    assert run[0] == "pass"
    assert head in run[1]
