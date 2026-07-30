"""ContextVar-first-then-env precedence for the epic-task status write site.

``update_status.update_task_status`` reads the done-verified guard and the
transition source from the request-scoped claim-bypass ContextVar first, then
the process-global env vars. These tests prove both directions at that site so
the done-transition cascade relay (ContextVar) and the historical env-driven
callers (merge/SKILL.md, done-transition.sh) both work.
"""

from __future__ import annotations

import io
from unittest import mock

import pytest

from runtime.api.conftest import insert_epic_task
from yoke_core.domain import status_claim_bypass_context as ctx
from yoke_core.domain import update_status

# Synthetic fixture id kept off the literal so the doc-hygiene drift guard stays clean.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"

_BYPASS_ENV_VARS = (
    "YOKE_CLAIM_BYPASS",
    "YOKE_STATUS_SOURCE",
    "YOKE_QA_GATE_BYPASS",
    "YOKE_TASK_DONE_VERIFIED",
)


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    for var in _BYPASS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _task_status(test_db, epic_id, task_num):
    row = test_db.execute(
        "SELECT status FROM epic_tasks WHERE epic_id = %s AND task_num = %s",
        (str(epic_id), str(task_num)),
    ).fetchone()
    return row[0] if row else None


class TestDoneGuardContextVar:
    def test_contextvar_done_verified_allows_done_with_no_env(self, test_db):
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="reviewed-implementation"
        )
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(update_status, "_history_insert"), \
             ctx.status_bypass_override(
                 claim_bypass=f"done-cascade:{TEST_ITEM_REF}",
                 status_source="",
                 task_done_verified=True,
             ):
            rc = update_status.update_task_status(
                test_db, "42", "1", "done", "",
                no_rebuild=True, no_github=True, no_derive=True,
                stdout=out, stderr=err,
            )
        assert rc == 0
        assert _task_status(test_db, 42, 1) == "done"

    def test_env_done_verified_still_allows_done(self, test_db, monkeypatch):
        insert_epic_task(
            test_db, epic_id=43, task_num=1, status="reviewed-implementation"
        )
        monkeypatch.setenv("YOKE_TASK_DONE_VERIFIED", "1")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(update_status, "_history_insert"), \
             mock.patch.object(update_status, "_verify_claim"):
            rc = update_status.update_task_status(
                test_db, "43", "1", "done", "",
                no_rebuild=True, no_github=True, no_derive=True,
                stdout=out, stderr=err,
            )
        assert rc == 0
        assert _task_status(test_db, 43, 1) == "done"

    def test_done_blocked_without_contextvar_or_env(self, test_db):
        insert_epic_task(
            test_db, epic_id=44, task_num=1, status="reviewed-implementation"
        )
        out, err = io.StringIO(), io.StringIO()
        rc = update_status.update_task_status(
            test_db, "44", "1", "done", "",
            no_rebuild=True, no_github=True, no_derive=True,
            stdout=out, stderr=err,
        )
        assert rc == 4
        assert "merge-verified" in err.getvalue()
        assert _task_status(test_db, 44, 1) == "reviewed-implementation"


class TestTransitionSourceContextVar:
    def _capture_source(self, monkeypatch):
        seen = {}

        def fake_record(conn, *, epic_id, task_num, from_status, to_status, source):
            seen["source"] = source

        monkeypatch.setattr(
            "yoke_core.domain.item_status_transitions.record_task_transition",
            fake_record,
        )
        # The generated-task activation gate (planned -> implementing) is
        # orthogonal to source attribution; a bare synthetic task has no scope
        # metadata, so stub the scope check to no issues and let the transition
        # reach the recorder these tests assert on.
        monkeypatch.setattr(
            "yoke_core.domain.epic_task_scope.task_scope_issues",
            lambda *a, **k: [],
        )
        return seen

    def test_source_from_contextvar_wins(self, test_db, monkeypatch):
        insert_epic_task(test_db, epic_id=45, task_num=1, status="planned")
        seen = self._capture_source(monkeypatch)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(update_status, "_history_insert"), \
             ctx.status_bypass_override(
                 claim_bypass="done-cascade:YOK-45",
                 status_source="my-cascade-source",
                 task_done_verified=False,
             ):
            update_status.update_task_status(
                test_db, "45", "1", "implementing", "",
                no_rebuild=True, no_github=True, no_derive=True,
                stdout=out, stderr=err,
            )
        assert seen["source"] == "my-cascade-source"

    def test_source_env_fallback_and_default(self, test_db, monkeypatch):
        insert_epic_task(test_db, epic_id=46, task_num=1, status="planned")
        seen = self._capture_source(monkeypatch)
        monkeypatch.setenv("YOKE_STATUS_SOURCE", "env-source")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(update_status, "_history_insert"), \
             mock.patch.object(update_status, "_verify_claim"):
            update_status.update_task_status(
                test_db, "46", "1", "implementing", "",
                no_rebuild=True, no_github=True, no_derive=True,
                stdout=out, stderr=err,
            )
        assert seen["source"] == "env-source"

    def test_source_defaults_when_nothing_set(self, test_db, monkeypatch):
        insert_epic_task(test_db, epic_id=47, task_num=1, status="planned")
        seen = self._capture_source(monkeypatch)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(update_status, "_history_insert"), \
             mock.patch.object(update_status, "_verify_claim"):
            update_status.update_task_status(
                test_db, "47", "1", "implementing", "",
                no_rebuild=True, no_github=True, no_derive=True,
                stdout=out, stderr=err,
            )
        assert seen["source"] == "update-status"
