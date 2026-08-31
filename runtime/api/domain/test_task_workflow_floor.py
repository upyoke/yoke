"""Floor task workflow: laneless activation and no-SHA close-out."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.lifecycle_status import LEGACY_STATUS_GLYPHS
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.dash_execution import (
    evaluate_dash_evidence,
    record_dash_evidence,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.direct_workflow_activation_gate import (
    evaluate_work_claim_activation,
)
from yoke_core.domain.floor_attestation import FLOOR_RUNG_AGENT_ATTESTED
from yoke_core.domain import floor_attestation_gate
from yoke_core.domain.item_worktree_lane_creation import (
    ItemWorktreeLaneCreationError,
    ensure_default_item_worktree_lane,
)
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_MERGE_FREE,
    WORKFLOW_QA_OPTIONAL,
    WORKFLOW_WORKTREES_NONE,
)
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.api import (
    service_client_structured_api_adapter as structured_api_adapter,
)
from yoke_core.domain import worktree_preflight


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


def test_task_definition_is_a_shared_vocabulary_subset() -> None:
    fixture = builtin_workflow_definition("task")
    definition = fixture["definition"]
    stages = tuple(stage["id"] for stage in definition["stages"])
    assert stages == ("idea", "implementing", "done")
    assert set(stages) <= set(LEGACY_STATUS_GLYPHS)
    policies = definition["policies"]
    assert policies["worktrees"] == WORKFLOW_WORKTREES_NONE
    assert policies["delivery"] == WORKFLOW_DELIVERY_MERGE_FREE
    assert policies["qa"] == WORKFLOW_QA_OPTIONAL
    assert policies["generated_children"] == "none"
    assert set(definition["entry_surfaces"]) == {
        "harness_skill",
        "cli",
        "web_form",
        "promotion",
    }


def test_dash_no_changes_closes_without_shas(test_db) -> None:
    insert_item(test_db, id=26820, workflow_id="dash")
    payload = record_dash_evidence(
        test_db,
        item_id=26820,
        result_summary="No code change was required.",
        verification_summary="Observed the live tree; nothing to edit.",
        verification_status="passed",
        commit_sha="",
        merge_sha="",
        touched_files=[],
        tree_root="",
        tree_head_sha="",
        no_changes=True,
        actor_id="2",
    )
    assert payload["floor_rung"] == FLOOR_RUNG_AGENT_ATTESTED
    assert payload["commit_sha"] == ""
    assert payload["merge_sha"] == ""
    verdict = evaluate_dash_evidence(test_db, 26820)
    assert verdict.satisfied is True
    assert verdict.missing == ()


class _NonClosingConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        return None


def test_task_floor_attestation_closes_without_shas(test_db, monkeypatch) -> None:
    insert_item(test_db, id=26821, workflow_id="task")
    record_dash_evidence(
        test_db,
        item_id=26821,
        result_summary="Folder project received the note.",
        verification_summary="Observed the folder; no git identity exists.",
        verification_status="passed",
        commit_sha="",
        merge_sha="",
        touched_files=["notes/readme.txt"],
        tree_root="",
        tree_head_sha="",
        no_changes=False,
        actor_id="2",
    )
    evidence = evaluate_dash_evidence(test_db, 26821).evidence or {}
    # Nobody passed the rung: merge-free delivery is what stamps it.
    assert evidence["floor_rung"] == FLOOR_RUNG_AGENT_ATTESTED
    assert evidence["actor_id"] == "2"
    assert evidence["touched_files"] == ["notes/readme.txt"]
    monkeypatch.setattr(
        floor_attestation_gate,
        "connect",
        lambda _path: _NonClosingConnection(test_db),
    )
    assert floor_attestation_gate.evaluate(
        item_id=26821, target_status="done", db_path="unused",
    ) is None


def test_task_activation_does_not_require_a_worktree(tmp_path, monkeypatch) -> None:
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            insert_item(conn, id=26822, workflow_id="task", status="idea")
            now = iso8601_now()
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, executor, provider, model, workspace, "
                "project_id, offered_at, last_heartbeat, actor_id) "
                "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s, 1)",
                ("task-floor", now, now),
            )
            conn.execute(
                "INSERT INTO work_claims "
                "(session_id, target_kind, scope, claim_type, claimed_at, "
                "last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
                ("task-floor", make_item_target(26822).scope_json(), now, now),
            )
            conn.commit()
        finally:
            conn.close()
        assert (
            evaluate_work_claim_activation(
                item_id=26822,
                target_status="implementing",
                db_path=db_path,
                session_id="task-floor",
            )
            is None
        )
        conn = connect_test_db(db_path)
        try:
            with pytest.raises(
                ItemWorktreeLaneCreationError, match="worktrees=none"
            ):
                ensure_default_item_worktree_lane(conn, item_id=26822)
        finally:
            conn.close()


def test_a_merging_workflow_still_owes_its_shas(test_db) -> None:
    """The floor is derived from delivery, so Dash cannot skip its SHAs."""
    insert_item(test_db, id=26823, workflow_id="dash")
    with pytest.raises(ValueError, match="7-64 character git SHA"):
        record_dash_evidence(
            test_db,
            item_id=26823,
            result_summary="Landed the change.",
            verification_summary="Suite green on the lane head.",
            verification_status="passed",
            commit_sha="",
            merge_sha="",
            touched_files=["packages/example.py"],
            tree_root="",
            tree_head_sha="",
            no_changes=False,
            actor_id="2",
        )


def test_a_folder_project_carries_a_task_without_a_repo(
    tmp_path, monkeypatch,
) -> None:
    """No git identity anywhere: activation still prepares no lane."""
    folder = tmp_path / "notes-project"
    folder.mkdir()
    item = {
        "id": 26824,
        "public_ref": "YOK-26824",
        "blocked": False,
        "workflow": {"policies": {"worktrees": WORKFLOW_WORKTREES_NONE}},
    }
    monkeypatch.setattr(
        structured_api_adapter,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=True, result={"item": item}, error=None,
        ),
    )
    monkeypatch.setattr(
        worktree_preflight, "claim_work", lambda _item_id: (True, "acquired"),
    )
    monkeypatch.setattr(
        worktree_preflight,
        "activate_path_claims",
        lambda _item_id: (True, "", []),
    )
    monkeypatch.setattr(
        worktree_preflight,
        "resolve_item_branch_and_lane",
        lambda _item_id: ("YOK-26824", ""),
    )

    outcome = worktree_preflight.run_preflight(
        item_id=26824,
        project=None,
        repo_root=None,
        actual_cwd=str(folder),
    )

    assert outcome.ok is True
    assert outcome.worktree_path == ""
    assert outcome.semantic_scope == "main"
    assert "worktree:skipped" in outcome.actions_taken
