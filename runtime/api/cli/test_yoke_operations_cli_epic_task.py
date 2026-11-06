"""Dispatch-path tests for ``yoke workflow-item epic-task ...``,
``yoke workflow-item epic-progress-note ...``, and ``yoke epic-tasks list``."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_epic_task_test_support import (_CAPTURED_REQUESTS as _CAPTURED_REQUESTS, _reset_captured as _reset_captured, _run as _run, _stub_fail as _stub_fail, _stub_ok as _stub_ok)
from runtime.api.cli.yoke_operations_cli_epic_review_test_support import (_run_capture as _run_capture)


class TestEpicTaskBodyReplace:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "body-replace",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--body",
            "new task body",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.body_replace"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num == 3
        assert req.payload == {"body": "new task body"}


class TestEpicTaskSplit:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "split",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--children-json",
            '[{"title":"Child A"},{"title":"Child B"}]',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.split"
        assert req.payload == {
            "children": [{"title": "Child A"}, {"title": "Child B"}],
        }

    def test_bad_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "split",
            "--epic",
            "YOK-1",
            "--task-num",
            "1",
            "--children-json",
            "{not-json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestEpicTaskReassign:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "reassign",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--new-worktree",
            "YOK-501-new",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.reassign"
        assert req.payload == {"new_worktree": "YOK-501-new"}


class TestEpicTaskAdd:
    def test_dispatches_minimal(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "add",
            "--epic",
            "YOK-501",
            "--title",
            "New task",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.add"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num is None
        assert req.payload == {
            "title": "New task",
            "body": "",
            "worktree": "",
            "context_estimate": "",
            "dependencies": "",
        }

    def test_dispatches_with_metadata(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "add",
            "--epic",
            "YOK-501",
            "--title",
            "Task X",
            "--body",
            "task body",
            "--worktree",
            "YOK-501-X",
            "--context-estimate",
            "2-3 sessions",
            "--dependencies",
            "1,2",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "title": "Task X",
            "body": "task body",
            "worktree": "YOK-501-X",
            "context_estimate": "2-3 sessions",
            "dependencies": "1,2",
        }


class TestEpicTaskRemove:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "remove",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--reason",
            "obsolete",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.remove"
        assert req.payload == {"reason": "obsolete"}


class TestEpicTaskMetadataUpdate:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "metadata-update",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--fields-json",
            '{"status":"in_progress","worktree":"YOK-501-3"}',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.metadata_update"
        assert req.payload == {
            "fields": {"status": "in_progress", "worktree": "YOK-501-3"},
        }

    def test_bad_fields_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "metadata-update",
            "--epic",
            "YOK-1",
            "--task-num",
            "1",
            "--fields-json",
            "[]",
        )
        assert rc == 2


class TestEpicProgressNote:
    def test_append_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-progress-note",
            "append",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--note-num",
            "1",
            "--body",
            "kickoff",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_progress_note.append"
        assert req.payload == {
            "note_num": 1,
            "body": "kickoff",
            "commit_hash": "",
        }

    def test_list_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-progress-note",
            "list",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--limit",
            "10",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_progress_note.list"
        assert req.payload == {"limit": 10, "offset": 0}
