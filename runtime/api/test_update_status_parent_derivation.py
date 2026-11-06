"""Parent status derivation follows generated-task progress and reports write failures."""

from __future__ import annotations
import io
from unittest import mock
from runtime.api.conftest import insert_item
from runtime.api.workflow_task_fixture_support import insert_epic_task
from runtime.api.update_status_test_helpers import item_field as _item_field
from yoke_core.domain import update_status


class TestAutoDerive:
    def test_all_tasks_terminal_derives_reviewing(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        insert_epic_task(test_db, epic_id=42, task_num=2, status="done")
        out = io.StringIO()
        err = io.StringIO()
        # Mock the owned in-process backlog update path.
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            return_value={"success": True},
        ) as mock_exec:
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "done",
                stdout=out,
                stderr=err,
            )
        assert "Auto-deriving" in out.getvalue()
        mock_exec.assert_called_once()
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["item_id"] == 42
        assert call_kwargs["field"] == "status"
        assert call_kwargs["value"] == "reviewing-implementation"

    def test_in_flight_derives_implementing(self, test_db):
        insert_item(test_db, id=42, title="Epic", workflow_id="epic", status="planned")
        insert_epic_task(test_db, epic_id=42, task_num=1, status="implementing")
        insert_epic_task(test_db, epic_id=42, task_num=2, status="planned")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            return_value={"success": True},
        ) as mock_exec:
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "implementing",
                stdout=out,
                stderr=err,
            )
        assert "Auto-deriving" in out.getvalue()
        assert "implementing" in out.getvalue()
        mock_exec.assert_called_once()

    def test_all_planned_derives_planned(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(test_db, epic_id=42, task_num=1, status="planned")
        insert_epic_task(test_db, epic_id=42, task_num=2, status="planned")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            return_value={"success": True},
        ):
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "planned",
                stdout=out,
                stderr=err,
            )
        assert "planned" in out.getvalue()

    def test_no_derive_when_parent_is_done(self, test_db):
        insert_item(test_db, id=42, title="Epic", workflow_id="epic", status="done")
        insert_epic_task(test_db, epic_id=42, task_num=1, status="implementing")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
        ) as mock_exec:
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "implementing",
                stdout=out,
                stderr=err,
            )
        assert not mock_exec.called
        assert out.getvalue() == ""

    def test_no_derive_when_same_status(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(test_db, epic_id=42, task_num=1, status="implementing")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
        ) as mock_exec:
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "implementing",
                stdout=out,
                stderr=err,
            )
        assert not mock_exec.called

    def test_planned_plus_blocked_derives_planned(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(test_db, epic_id=42, task_num=1, status="planned")
        insert_epic_task(test_db, epic_id=42, task_num=2, status="blocked")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            return_value={"success": True},
        ):
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "planned",
                stdout=out,
                stderr=err,
            )
        assert "planned" in out.getvalue()


class TestAutoDeriveWriteErrors:
    """auto_derive_epic_status error paths with shell-fixture injection."""

    def test_write_failure_warns(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(test_db, epic_id=42, task_num=1, status="done")
        insert_epic_task(
            test_db, epic_id=42, task_num=2, status="reviewed-implementation"
        )
        insert_epic_task(
            test_db, epic_id=42, task_num=3, status="reviewed-implementation"
        )
        out = io.StringIO()
        err = io.StringIO()

        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            return_value={"success": False, "error": "SIMULATED_PARENT_WRITE_FAILURE"},
        ):
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "done",
                stdout=out,
                stderr=err,
            )

        assert "parent-status write failed" in err.getvalue()
        assert _item_field(test_db, 42, "status") == "implementing"

    def test_postwrite_verify_mismatch_warns(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(test_db, epic_id=42, task_num=1, status="done")
        insert_epic_task(
            test_db, epic_id=42, task_num=2, status="reviewed-implementation"
        )
        insert_epic_task(
            test_db, epic_id=42, task_num=3, status="reviewed-implementation"
        )
        out = io.StringIO()
        err = io.StringIO()

        # execute_update returns success, but the DB status was never actually
        # updated — mirrors the SIMULATED_PARENT_WRITE_NOOP integration-test case.
        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            return_value={"success": True},
        ):
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "done",
                stdout=out,
                stderr=err,
            )

        assert "post-write verification failed" in err.getvalue()
        assert _item_field(test_db, 42, "status") == "implementing"

    def test_execute_update_raises_logs_warning(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", status="implementing"
        )
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        insert_epic_task(test_db, epic_id=42, task_num=2, status="done")
        out = io.StringIO()
        err = io.StringIO()

        with mock.patch(
            "yoke_core.domain.backlog.execute_update",
            side_effect=RuntimeError("boom"),
        ):
            update_status.auto_derive_epic_status(
                test_db,
                "42",
                "done",
                stdout=out,
                stderr=err,
            )

        assert "parent-status write raised" in err.getvalue()
