"""In-process coverage for the recorded-survey status read.

* In-process: the ``direct_workflow.conflict_survey.status`` handler run
  directly against a seeded Postgres ``test_db`` returns the recorded
  survey plus a fresh conflict re-check (found / not-found / contacts),
  which is the local-Postgres in-process dispatch path.

* Relay routing lives in ``test_worktree_prepare_relay_routing``, which
  drives the same reads through ``call_dispatcher`` instead of a
  connection.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from runtime.api.domain.closing_connection_test_support import closing_connection

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import db_helpers
from yoke_core.domain.conflict_survey import record_conflict_survey, survey_conflicts
from yoke_core.domain.handlers import direct_workflow_conflict_survey_status as status_mod
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.conflict_survey import (
    DURABLE_ABSENT,
    DURABLE_PENDING,
    DURABLE_RECORDED,
    DURABLE_UNREADABLE,
)


@pytest.fixture(autouse=True)
def _item_sections_contract(test_db):
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()


def _status_request(item_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="direct_workflow.conflict_survey.status",
        actor=ActorContext(actor_id="op", session_id="s-status"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
    )


def _call_status_closing(monkeypatch, test_db, item_id: int):
    @contextmanager
    def _use():
        with closing_connection(test_db) as proxy:
            yield proxy
    monkeypatch.setattr(db_helpers, "connect", _use)
    return status_mod.handle_conflict_survey_status(_status_request(item_id))


def _call_status(monkeypatch, test_db, item_id: int):
    @contextmanager
    def _use():
        yield test_db

    monkeypatch.setattr(db_helpers, "connect", _use)
    return status_mod.handle_conflict_survey_status(_status_request(item_id))


# ---------------------------------------------------------------------------
# In-process (local-Postgres) handler proofs
# ---------------------------------------------------------------------------


def test_status_reports_recorded_clear_survey(test_db, monkeypatch):
    insert_item(test_db, id=3201, workflow_id="dash", title="Clear change")
    recorded = survey_conflicts(
        test_db, item_id=3201, touch_paths=["src/isolated_change.py"],
    )
    assert recorded.clear is True
    record_conflict_survey(test_db, recorded)

    outcome = _call_status(monkeypatch, test_db, 3201)

    assert outcome.primary_success is True
    payload = outcome.result_payload
    assert payload["found"] is True
    assert payload["durable_state"] == DURABLE_RECORDED
    assert payload["clear"] is True
    assert payload["workflow_id"] == "dash"
    assert payload["touch_paths"] == ["src/isolated_change.py"]
    assert payload["integration_target"] == "main"
    assert payload["fingerprint"]
    assert payload["blockers"] == []


def test_status_reports_not_found_without_recorded_survey(test_db, monkeypatch):
    insert_item(test_db, id=3202, workflow_id="dash", title="No survey yet")

    outcome = _call_status(monkeypatch, test_db, 3202)

    assert outcome.primary_success is True
    payload = outcome.result_payload
    assert payload["found"] is False
    assert payload["durable_state"] == DURABLE_ABSENT
    assert payload["clear"] is False
    assert payload["workflow_id"] == "dash"
    assert payload["touch_paths"] == []
    assert payload["blockers"] == []


@pytest.mark.parametrize(("item_id", "content", "durable_state"), [
    (3205, '{"pending_request":"request"}', DURABLE_PENDING),
    (3206, "{", DURABLE_UNREADABLE),
])
def test_status_classifies_nonrecorded_durable_rows(
    test_db, monkeypatch, item_id, content, durable_state,
):
    insert_item(test_db, id=item_id, workflow_id="dash", title="Incomplete survey")
    test_db.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, source, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, "Conflict Survey", content, "direct-workflow", "now", "now"),
    )
    test_db.commit()

    outcome = _call_status(monkeypatch, test_db, item_id)

    assert outcome.primary_success is True
    assert outcome.result_payload["durable_state"] == durable_state
    assert outcome.result_payload["found"] is False


def test_status_reports_blocked_survey(test_db, monkeypatch):
    insert_item(test_db, id=3203, workflow_id="dash", title="Contended change")
    insert_item(
        test_db,
        id=3204,
        workflow_id="dash",
        title="Registered work",
        spec="## File Budget\n\n- `src/contended.py`\n",
    )
    recorded = survey_conflicts(
        test_db, item_id=3203, touch_paths=["src/contended.py"],
    )
    assert recorded.clear is False
    record_conflict_survey(test_db, recorded)

    outcome = _call_status(monkeypatch, test_db, 3203)

    payload = outcome.result_payload
    assert payload["found"] is True
    assert payload["clear"] is False
    assert any(
        blocker["kind"] == "frontier_scope" and blocker["owner_item_id"] == 3204
        for blocker in payload["blockers"]
    )


def test_status_rejects_non_item_target():
    request = FunctionCallRequest(
        function="direct_workflow.conflict_survey.status",
        actor=ActorContext(actor_id="op", session_id="s-x"),
        target=TargetRef(kind="global"),
        payload={},
    )
    outcome = status_mod.handle_conflict_survey_status(request)
    assert outcome.primary_success is False
    assert outcome.error.code == "invalid_target"


def test_status_names_blockers_before_the_connection_closes(
    test_db, monkeypatch,
):
    """Regression: the blocker names were read after the block exited."""
    insert_item(test_db, id=3205, workflow_id="dash", title="Contended")
    insert_item(
        test_db,
        id=3206,
        workflow_id="dash",
        title="Registered work",
        spec="## File Budget\n\n- `src/late_read.py`\n",
    )
    recorded = survey_conflicts(
        test_db, item_id=3205, touch_paths=["src/late_read.py"],
    )
    assert recorded.clear is False
    record_conflict_survey(test_db, recorded)

    outcome = _call_status_closing(monkeypatch, test_db, 3205)

    assert outcome.primary_success is True
    blockers = outcome.result_payload["blockers"]
    assert blockers
    assert all(blocker["owner_public_ref"] for blocker in blockers)
