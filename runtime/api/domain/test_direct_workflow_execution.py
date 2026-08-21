"""Direct-workflow survey, evidence, and promotion contracts."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import (
    conflict_survey_gate,
    dash_evidence_gate,
    doc_completion_gate,
)
from yoke_core.domain.conflict_survey import (
    record_conflict_survey,
    survey_conflicts,
)
from yoke_core.domain.dash_execution import (
    evaluate_dash_evidence,
    record_dash_escalation,
    record_dash_evidence,
)
from yoke_core.domain.field_note_dash_promotion import (
    ensure_field_note_dash_promotion_schema,
    promote_field_note_to_dash,
)
from yoke_core.domain.handlers.direct_workflow_execution import (
    REGISTRATIONS as EXECUTION_REGISTRATIONS,
)
from yoke_core.domain.handlers.field_note_dash_promotion import (
    REGISTRATIONS as PROMOTION_REGISTRATIONS,
)
from yoke_core.domain.strategy_execution_schema import (
    ensure_strategy_execution_schema,
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


def test_conflict_survey_preserves_dot_paths_and_finds_frontier_scope(test_db):
    insert_item(test_db, id=2101, workflow_id="dash", title="Small change")
    insert_item(
        test_db,
        id=2102,
        workflow_id="dash",
        title="Registered work",
        spec=(
            "## File Budget\n\n"
            "- `.agents/skills/yoke/dash/SKILL.md`\n"
        ),
    )

    result = survey_conflicts(
        test_db,
        item_id=2101,
        touch_paths=["./.agents/skills/yoke/dash/SKILL.md"],
    )
    record_conflict_survey(test_db, result)

    assert result.clear is False
    assert result.touch_paths == (".agents/skills/yoke/dash/SKILL.md",)
    assert any(
        blocker.kind == "frontier_scope"
        and blocker.owner_item_id == 2102
        for blocker in result.blockers
    )
    stored = test_db.execute(
        "SELECT content FROM item_sections "
        "WHERE item_id = %s AND section_name = 'Conflict Survey'",
        (2101,),
    ).fetchone()
    assert json.loads(stored[0])["fingerprint"] == result.fingerprint


def test_conflict_survey_reads_linked_blitz_execution_budget(test_db):
    ensure_strategy_execution_schema(test_db)
    insert_item(test_db, id=2103, workflow_id="dash", title="Candidate")
    insert_item(
        test_db,
        id=2104,
        workflow_id="blitz",
        title="Document-led frontier",
        spec="",
    )
    project_id = test_db.execute(
        "SELECT project_id FROM items WHERE id = %s", (2104,),
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO strategy_docs "
        "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s)",
        (
            project_id,
            "EXECUTION-PLAN",
            "## File Budget\n\n- `src/document-owned.py`\n",
            "2026-07-28T00:00:00Z",
        ),
    )
    test_db.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (%s, %s, %s, %s)",
        (2104, project_id, "EXECUTION-PLAN", "2026-07-28T00:00:00Z"),
    )
    test_db.commit()

    result = survey_conflicts(
        test_db,
        item_id=2103,
        touch_paths=["src/document-owned.py"],
    )

    assert result.clear is False
    assert any(
        blocker.kind == "frontier_scope"
        and blocker.owner_item_id == 2104
        for blocker in result.blockers
    )
    assert test_db.execute(
        "SELECT spec FROM items WHERE id = %s", (2104,),
    ).fetchone()[0] == ""
def test_dash_evidence_cannot_self_attest_enabled_posture(test_db):
    insert_item(
        test_db,
        id=2110,
        workflow_id="dash",
        workflow_posture=json.dumps({
            "approval_on_done": True,
            "deployment": True,
        }),
    )
    record_dash_evidence(
        test_db,
        item_id=2110,
        result_summary="Updated the generated footer.",
        verification_summary="Focused UI test passed.",
        verification_status="passed",
        commit_sha="abc1234",
        merge_sha="def5678",
        touched_files=["ui/footer.js"],
        tree_root="/repo/.worktrees/lane", tree_head_sha="abc1234",
        posture_checks={"deployment": "completed"},
    )
    evidence = evaluate_dash_evidence(test_db, 2110)
    assert evidence.satisfied is True
    assert evidence.missing == ()
    assert evidence.evidence["posture_checks"] == {"deployment": "completed"}


def test_dash_escalation_is_a_machine_readable_item_link(test_db):
    insert_item(test_db, id=2120, workflow_id="dash")
    insert_item(test_db, id=2121, workflow_id="issue")

    payload = record_dash_escalation(
        test_db,
        item_id=2120,
        findings="The change needs a data migration and coordinated rollout.",
        issue_item_id=2121,
        issue_ref="YOK-2121",
    )

    assert payload["dash_item_id"] == 2120
    assert payload["issue_item_id"] == 2121
    assert payload["issue_ref"] == "YOK-2121"


def test_field_note_promotion_is_idempotent(
    test_db,
    monkeypatch,
):
    ensure_field_note_dash_promotion_schema(test_db)
    test_db.execute(
        "INSERT INTO ouroboros_entries "
        "(id, timestamp, agent, category, body, created_at, project_id) "
        "VALUES (22890, '2026-07-26T00:00:00Z', 'codex', "
        "'field-note-observation', 'Tighten this focused behavior.', "
        "'2026-07-26T00:00:00Z', 1)",
    )
    test_db.commit()

    from yoke_core.domain import backlog_create_op

    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        insert_item(test_db, id=2130, workflow_id="dash", title=kwargs["title"])
        return {"success": True, "item_id": 2130, "item_ref": "YOK-2130"}

    monkeypatch.setattr(backlog_create_op, "execute_create", _create)
    first = promote_field_note_to_dash(
        test_db,
        entry_id=22890,
        title="Tighten focused behavior",
        instruction=None,
        project=None,
        priority=None,
        workflow_posture=None,
        actor_id=1,
        session_id="session-a",
    )
    second = promote_field_note_to_dash(
        test_db,
        entry_id=22890,
        title="Ignored repeat title",
        instruction="Ignored repeat instruction",
        project="yoke",
        priority=None,
        workflow_posture=None,
        actor_id=1,
        session_id="session-a",
    )

    assert first.created is True
    assert second.created is False
    assert second.dash_item_id == first.dash_item_id == 2130
    assert len(calls) == 1
    assert calls[0]["entry_surface"] == "promotion"
    assert calls[0]["workflow"] == "dash"


def test_registered_execution_functions_keep_claim_boundaries_explicit():
    registrations = {
        row["function_id"]: row
        for row in [*EXECUTION_REGISTRATIONS, *PROMOTION_REGISTRATIONS]
    }

    assert registrations["direct_workflow.dash.survey"][
        "claim_required_kind"
    ] is None
    assert registrations["direct_workflow.blitz.survey"][
        "claim_required_kind"
    ] is None
    assert registrations["direct_workflow.dash.evidence"][
        "claim_required_kind"
    ] == "item"
    assert registrations["direct_workflow.dash.escalate"][
        "claim_required_kind"
    ] == "item"
    assert registrations["ouroboros.field_note.promote"][
        "claim_required_kind"
    ] is None


class _NonClosingConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        return None


def test_conflict_survey_gate_allows_recorded_overlap(
    test_db,
    monkeypatch,
):
    insert_item(test_db, id=2140, workflow_id="dash")
    initial = survey_conflicts(
        test_db, item_id=2140, touch_paths=["src/direct.py"],
    )
    assert initial.clear is True
    record_conflict_survey(test_db, initial)
    insert_item(
        test_db,
        id=2141,
        workflow_id="issue",
        spec="## File Budget\n\n- `src/direct.py`\n",
    )
    monkeypatch.setattr(
        conflict_survey_gate,
        "connect",
        lambda _path: _NonClosingConnection(test_db),
    )

    verdict = conflict_survey_gate.evaluate(
        item_id=2140,
        target_status="implementing",
        db_path="unused",
    )

    assert verdict is None


def test_dash_evidence_gate_accepts_complete_close_record(
    test_db,
    monkeypatch,
):
    insert_item(test_db, id=2150, workflow_id="dash")
    record_dash_evidence(
        test_db,
        item_id=2150,
        result_summary="Completed the requested change.",
        verification_summary="Focused verification passed.",
        verification_status="passed",
        commit_sha="abc1234",
        merge_sha="def5678",
        touched_files=["src/direct.py"],
        tree_root="/repo/.worktrees/lane", tree_head_sha="abc1234",
    )
    monkeypatch.setattr(
        dash_evidence_gate,
        "connect",
        lambda _path: _NonClosingConnection(test_db),
    )

    assert dash_evidence_gate.evaluate(
        item_id=2150,
        target_status="done",
        db_path="unused",
    ) is None


def test_doc_completion_gate_names_missing_document_evidence(monkeypatch):
    connection = _NonClosingConnection(object())
    monkeypatch.setattr(
        doc_completion_gate, "connect", lambda _path: connection,
    )
    monkeypatch.setattr(
        doc_completion_gate,
        "blitz_completion_evidence",
        lambda _conn, _item_id: {
            "satisfied": False,
            "missing": ["remaining_work", "parent_reconciliation"],
        },
    )

    blocked = doc_completion_gate.evaluate(
        item_id=2160,
        target_status="done",
        db_path="unused",
    )

    assert blocked["error_code"] == "GATE_DOC_COMPLETION_UNSATISFIED"
    assert "remaining_work" in blocked["error"]
    assert "parent_reconciliation" in blocked["error"]
