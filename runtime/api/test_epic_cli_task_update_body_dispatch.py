"""AC-8.3 dispatcher-parity tests for ``epic task-update-body``.

Companion to :mod:`test_epic_cli`. Verifies that
``python3 -m yoke_core.domain.epic task-update-body <epic> <num>``
routes through :func:`yoke_core.domain.yoke_function_dispatch.dispatch`
for ``workflow_item.epic_task.body_replace`` (not via the legacy direct
``task_update_body`` call).

Each test patches the handler's ``epic_task_crud.task_update_body``
binding to assert the dispatcher hop, and silences ``verify_claim`` so the
test stays focused on CLI-to-dispatcher routing rather than work-claim
ownership. The fixture uses the disposable Postgres test database seam so
the dispatcher handler opens its normal backend connection.
"""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest

from yoke_core.domain import epic
from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from runtime.api.fixtures.pg_testdb import test_database


@pytest.fixture
def db():
    """Fresh Postgres fixture seeded with one epic row.

    Mirrors the fixture in ``test_epic_cli`` so the two test files share
    behavior expectations.
    """
    with test_database() as conn:
        insert_item(conn, id=42, type="epic", status="planning", title="Epic Title")
        insert_epic_task(
            conn, epic_id=42, task_num=1, title="Task One",
            status="planning", body="",
        )
        yield conn


class TestTaskUpdateBodyDispatchParity:
    """AC-8.3 — ``task-update-body`` builds and dispatches the
    ``workflow_item.epic_task.body_replace`` request."""

    def test_body_file_path_routes_through_dispatcher(self, db, tmp_path):
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        from yoke_core.domain.handlers import workflow_item_epic_task as task_handler

        body_file = tmp_path / "body.md"
        body_file.write_text("Body from file")

        with patch("yoke_core.domain.epic._validate_epic_exists"), patch.object(
            task_handler.epic_task_crud, "task_update_body", return_value="ok",
        ) as handler, patch.object(
            dispatch_module, "verify_claim", return_value=None,
        ):
            epic.main(["task-update-body", "42", "1", "--body-file", str(body_file)])

        assert handler.called
        args = handler.call_args[0]
        assert args[1] == "42"
        assert args[2] == 1
        assert args[3] == "Body from file"

    def test_stdin_path_routes_through_dispatcher(self, db):
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        from yoke_core.domain.handlers import workflow_item_epic_task as task_handler

        with patch("yoke_core.domain.epic._validate_epic_exists"), patch(
            "yoke_core.domain.epic._read_stdin_safe",
            return_value="Body from stdin",
        ), patch.object(
            task_handler.epic_task_crud, "task_update_body", return_value="ok",
        ) as handler, patch.object(
            dispatch_module, "verify_claim", return_value=None,
        ):
            epic.main(["task-update-body", "42", "1"])

        assert handler.called
        args = handler.call_args[0]
        assert args[1] == "42"
        assert args[2] == 1
        assert args[3] == "Body from stdin"

    def test_json_mode_emits_function_call_response_envelope(self, db):
        """AC-8.5 — ``--json`` emits the FunctionCallResponse envelope verbatim."""
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        from yoke_core.domain.handlers import workflow_item_epic_task as task_handler

        out = StringIO()
        with patch("yoke_core.domain.epic._validate_epic_exists"), patch(
            "yoke_core.domain.epic._read_stdin_safe", return_value="X\n",
        ), patch.object(
            task_handler.epic_task_crud, "task_update_body", return_value="ok",
        ), patch.object(
            dispatch_module, "verify_claim", return_value=None,
        ), redirect_stdout(out):
            epic.main(["task-update-body", "42", "1", "--json"])

        envelope = json.loads(out.getvalue())
        assert envelope["success"] is True
        assert envelope["function"] == "workflow_item.epic_task.body_replace"
        result = envelope["result"]
        for key in ("epic_id", "task_num", "old_line_count", "new_line_count"):
            assert key in result
