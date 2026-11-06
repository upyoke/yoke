"""Comprehensive pytest suite for ``yoke_core.domain.update_status``.

Tests the Python-owned epic-task status mutation orchestration:
  - Core DB update (status, heartbeat, dispatch_attempts, history)
  - auto_unblock (blocked task dependency resolution)
  - auto_derive_epic_status (parent epic status recomputation)
  - Claim verification guard
  - Done guard

GitHub-side mocks (label sync, comment, close, checkbox), repo
resolution, and CLI shape live in
``runtime/api/test_update_status_github.py``.

Uses the shared ``test_db`` fixture from ``conftest.py`` for in-memory DB.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.conftest import insert_item
from runtime.api.workflow_task_fixture_support import insert_epic_task
from yoke_core.domain import update_status
from runtime.api.update_status_test_helpers import (
    task_field as _task_field,
    update as _update,
)


# ---------------------------------------------------------------------------
# Core DB Update
# ---------------------------------------------------------------------------


class TestCoreUpdate:
    def test_basic_status_update(self, test_db):
        insert_item(test_db, id=42, workflow_id="epic", status="planned")
        insert_epic_task(test_db, epic_id=42, task_num=1, status="planned")
        rc, out, _ = _update(test_db, 42, 1, "implementing")
        assert rc == 0
        assert "planned → implementing" in out
        assert _task_field(test_db, 42, 1, "status") == "implementing"

    def test_heartbeat_updated(self, test_db):
        insert_item(test_db, id=42, workflow_id="epic", status="planned")
        insert_epic_task(test_db, epic_id=42, task_num=1, status="planned")
        _update(test_db, 42, 1, "implementing")
        hb = _task_field(test_db, 42, 1, "last_heartbeat")
        assert hb is not None

    def test_dispatch_attempts_incremented_on_implementing(self, test_db):
        insert_item(test_db, id=42, workflow_id="epic", status="planned")
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="planned", dispatch_attempts=2
        )
        _update(test_db, 42, 1, "implementing")
        da = _task_field(test_db, 42, 1, "dispatch_attempts")
        assert da == 3

    def test_dispatch_attempts_not_incremented_on_other_status(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="implementing", dispatch_attempts=2
        )
        # Need pipeline for terminal status
        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.object(update_status, "_history_insert"),
            mock.patch.object(update_status, "_verify_claim"),
            mock.patch.dict(os.environ, {"YOKE_TASK_DONE_VERIFIED": "1"}),
        ):
            update_status.update_task_status(
                test_db,
                "42",
                "1",
                "reviewed-implementation",
                "",
                no_github=True,
                stdout=out,
                stderr=err,
            )
        da = _task_field(test_db, 42, 1, "dispatch_attempts")
        assert da == 2

    def test_noop_on_same_status_no_note(self, test_db):
        insert_item(test_db, id=42, workflow_id="epic", status="planned")
        insert_epic_task(test_db, epic_id=42, task_num=1, status="implementing")
        rc, out, _ = _update(test_db, 42, 1, "implementing")
        assert rc == 0
        assert out == ""

    def test_task_not_found(self, test_db):
        rc, _, err = _update(test_db, 99, 1, "implementing")
        assert rc == 1
        assert "not found" in err

    def test_invalid_status(self, test_db):
        insert_epic_task(test_db, epic_id=42, task_num=1, status="planned")
        rc, _, err = _update(test_db, 42, 1, "bogus-status")
        assert rc == 1
        assert "invalid" in err


# ---------------------------------------------------------------------------
# Done Guard
# ---------------------------------------------------------------------------


class TestDoneGuard:
    def test_done_blocked_without_verified(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        rc, _, err = _update(test_db, 42, 1, "done")
        assert rc == 4
        assert "merge-verified" in err

    def test_done_allowed_with_verified(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.object(update_status, "_history_insert"),
            mock.patch.object(update_status, "_verify_claim"),
            mock.patch.dict(os.environ, {"YOKE_TASK_DONE_VERIFIED": "1"}),
        ):
            rc = update_status.update_task_status(
                test_db,
                "42",
                "1",
                "done",
                "",
                no_github=True,
                stdout=out,
                stderr=err,
            )
        assert rc == 0
        assert _task_field(test_db, 42, 1, "status") == "done"


# ---------------------------------------------------------------------------
# Auto-unblock
# ---------------------------------------------------------------------------


class TestAutoUnblock:
    def test_unblocks_when_dep_met(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        insert_epic_task(
            test_db, epic_id=42, task_num=2, status="blocked", dependencies="1"
        )
        out = io.StringIO()
        with (
            mock.patch.object(update_status, "_history_insert"),
            mock.patch.object(update_status, "_verify_claim"),
        ):
            update_status.auto_unblock(
                test_db,
                "42",
                "1",
                "reviewed-implementation",
                stdout=out,
            )
        assert _task_field(test_db, 42, 2, "status") == "planned"
        assert "Auto-unblocking task 2" in out.getvalue()

    def test_stays_blocked_when_dep_not_met(self, test_db):
        insert_epic_task(test_db, epic_id=42, task_num=1, status="implementing")
        insert_epic_task(
            test_db, epic_id=42, task_num=2, status="blocked", dependencies="1"
        )
        out = io.StringIO()
        update_status.auto_unblock(test_db, "42", "1", "implementing", stdout=out)
        assert _task_field(test_db, 42, 2, "status") == "blocked"

    def test_multi_dep_all_must_be_met(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        insert_epic_task(test_db, epic_id=42, task_num=2, status="planned")
        insert_epic_task(
            test_db, epic_id=42, task_num=3, status="blocked", dependencies="1,2"
        )
        out = io.StringIO()
        with (
            mock.patch.object(update_status, "_history_insert"),
            mock.patch.object(update_status, "_verify_claim"),
        ):
            update_status.auto_unblock(
                test_db,
                "42",
                "1",
                "reviewed-implementation",
                stdout=out,
            )
        # Task 2 is not terminal, so task 3 stays blocked
        assert _task_field(test_db, 42, 3, "status") == "blocked"

    def test_no_deps_stays_blocked(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        insert_epic_task(
            test_db, epic_id=42, task_num=2, status="blocked", dependencies=""
        )
        out = io.StringIO()
        update_status.auto_unblock(
            test_db, "42", "1", "reviewed-implementation", stdout=out
        )
        assert _task_field(test_db, 42, 2, "status") == "blocked"


# ---------------------------------------------------------------------------
# Auto-derive parent epic status
# ---------------------------------------------------------------------------
