"""External task commits bind the candidate consumed by review insertion."""

from runtime.api.conftest import insert_epic_task
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.test_head_moving_hooks import (
    _bridge, _commit, _fired, _git, _hooked_repo,
)
from yoke_cli.commands import git_hook
from yoke_cli.main import main as cli_main
from yoke_core.domain import epic
from yoke_core.domain.item_worktrees import record_item_worktree


class BorrowedConnection:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def close(self):
        pass


def test_external_task_commit_records_head_and_accepts_review(
    tmp_path, test_db, monkeypatch,
):
    repo, env, log = _hooked_repo(tmp_path)
    _commit(repo, env, "seed")
    lane = repo / ".worktrees" / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(lane), env=env)
    _fired(log)
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
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda *_a, **_k: BorrowedConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_execution.connect", lambda *_a, **_k: BorrowedConnection(test_db),
    )
    chunked = "yoke_cli.commands.adapters.project_snapshot_chunked"
    monkeypatch.setattr(f"{chunked}.call_dispatcher", _bridge)
    monkeypatch.setattr(f"{chunked}.ensure_handlers_loaded", lambda: None)
    seen_roots = []

    def mapped_project(root):
        seen_roots.append(root)
        return "external" if root == str(repo.resolve()) else "yoke"

    monkeypatch.setattr("yoke_cli.config.machine_config.project_id", mapped_project)
    monkeypatch.setenv("YOKE_PROJECT_ID", "yoke")
    monkeypatch.setenv("YOKE_PROJECT", "yoke")
    monkeypatch.setenv("YOKE_RESOLVE_CWD", str(tmp_path))
    monkeypatch.delenv(git_hook.HEAD_RECORDING_SKIP_ENV, raising=False)
    _commit(lane, env, "task-change")
    head = _git(lane, "rev-parse", "HEAD")
    monkeypatch.chdir(lane)
    # Drive the actual installed shim's invocation through its real client
    # and server handler, retaining the disposable database in this process.
    fired = _fired(log)
    assert [hook for hook, _, _ in fired] == ["post-commit"]
    for hook, observed, args in fired:
        assert observed == head
        assert cli_main(["git", hook, *args]) == 0
    assert seen_roots == [str(repo.resolve())]
    assert test_db.execute(
        "SELECT commit_sha FROM item_worktrees WHERE id=%s", (lane_id,),
    ).fetchone()[0] == head

    result = epic.review_insert(test_db, str(item_id), 1, "PASS", "Reviewed", head_sha=head)

    assert "verdict=PASS" in result
    run = test_db.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE qa_requirement_id=%s",
        (requirement["id"],),
    ).fetchone()
    assert run[0] == "pass"
    assert head in run[1]


def test_missing_checkout_registration_teaches_repair(monkeypatch, capsys):
    monkeypatch.setattr("yoke_cli.config.machine_config.project_id", lambda _root: None)
    monkeypatch.delenv(git_hook.HEAD_RECORDING_SKIP_ENV, raising=False)
    assert cli_main(["git", "post-commit"]) == 0
    diagnostic = capsys.readouterr().err
    assert "checkout_project_unavailable" in diagnostic
    assert "yoke project register" in diagnostic
    assert "yoke project snapshot sync --head-only" in diagnostic
