"""No-change Dash skips git isolation and restores it before edits."""

from __future__ import annotations

import json
from contextlib import contextmanager

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_contracts.conflict_survey import DURABLE_RECORDED
from yoke_core.domain import db_helpers
from yoke_core.domain import direct_workflow_activation_gate as activation
from yoke_core.domain import direct_workflow_worktree_preflight as preflight
from yoke_core.domain.handlers.direct_workflow_execution import handle_dash_survey
from yoke_core.domain.workflow_behavior import WorktreeLanePolicy
from yoke_core.domain.worktree_preflight_outcome import WorktreePreflightOutcome

_LANE_REQUIRED = WorktreeLanePolicy(
    allowed_roles=frozenset({"implementation"}),
    required_roles=frozenset({"implementation"}),
)


@contextmanager
def _use_connection(connection):
    yield connection


def _request(function: str, item_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="test", session_id="session"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _survey_status(*, no_changes: bool) -> dict:
    return {
        "found": True,
        "clear": True,
        "touch_paths": [] if no_changes else ["src/x.py"],
        "no_changes": no_changes,
        "durable_state": DURABLE_RECORDED,
    }


def _capture_prepare(monkeypatch, *, no_changes: bool) -> dict:
    captured: dict = {}

    def _dispatch(*, function_id, **_kwargs):
        if function_id == "items.detail.get":
            return FunctionCallResponse(
                success=True,
                function=function_id,
                version="v1",
                result={"item": {"id": 7102, "workflow": {"id": "dash"}}},
            )
        if function_id == "direct_workflow.conflict_survey.status":
            return FunctionCallResponse(
                success=True,
                function=function_id,
                version="v1",
                result=_survey_status(no_changes=no_changes),
            )
        raise AssertionError(function_id)

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatch,
    )

    def fake_preflight(**kwargs):
        captured.update(kwargs)
        out = WorktreePreflightOutcome(ok=True, item_id=7102)
        if kwargs.get("no_worktree"):
            out.actions_taken.append("worktree:skipped")
        else:
            out.worktree_path = "/repo/.worktrees/ITEM"
            out.actions_taken.append("worktree:created")
        return out

    monkeypatch.setattr(preflight, "run_preflight", fake_preflight)
    return captured


def test_no_change_prepare_skips_the_git_lane(monkeypatch, capsys):
    captured = _capture_prepare(monkeypatch, no_changes=True)

    assert preflight.run(["YOK-7102", "--workflow", "dash", "--json"]) == 0
    assert captured["no_worktree"] is True
    assert captured["prepare_path_claims"] is None
    envelope = json.loads(capsys.readouterr().out)
    assert "worktree:skipped" in envelope["actions_taken"]
    assert any("no-change" in note for note in envelope["notes"])


def test_path_survey_prepare_still_creates_a_lane(monkeypatch, capsys):
    captured = _capture_prepare(monkeypatch, no_changes=False)

    assert preflight.run(["YOK-7102", "--workflow", "dash", "--json"]) == 0
    assert captured["no_worktree"] is False
    assert captured["prepare_path_claims"] is not None
    envelope = json.loads(capsys.readouterr().out)
    assert "worktree:created" in envelope["actions_taken"]


def _force_lane_policy(monkeypatch) -> None:
    monkeypatch.setattr(
        activation, "worktree_lane_policy", lambda _runtime: _LANE_REQUIRED
    )
    monkeypatch.setattr(
        activation, "load_item_workflow_runtime", lambda *_a, **_k: object()
    )


def _claimed_dash(test_db, item_id: int, session_id: str) -> None:
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()
    insert_item(test_db, id=item_id, workflow_id="dash", title="No change")
    insert_session(test_db, session_id)
    insert_item_claim(test_db, session_id, item_id)


def test_no_change_activation_skips_the_worktree(test_db, monkeypatch):
    item_id = 7103
    _claimed_dash(test_db, item_id, "session")
    monkeypatch.setattr(db_helpers, "connect", lambda: _use_connection(test_db))
    recorded = handle_dash_survey(
        _request(
            "direct_workflow.dash.survey",
            item_id,
            {"paths": [], "path_sizes": [], "no_changes": True},
        )
    )
    assert recorded.primary_success is True
    _force_lane_policy(monkeypatch)
    assert (
        activation.evaluate_work_claim_activation(
            item_id=item_id,
            target_status="implementing",
            db_path="unused",
            session_id="session",
            conn=test_db,
        )
        is None
    )


def test_path_survey_activation_still_requires_a_worktree(test_db, monkeypatch):
    item_id = 7104
    _claimed_dash(test_db, item_id, "session")
    monkeypatch.setattr(db_helpers, "connect", lambda: _use_connection(test_db))
    recorded = handle_dash_survey(
        _request(
            "direct_workflow.dash.survey",
            item_id,
            {"paths": ["src/x.py"], "path_sizes": [{
                "path": "src/x.py",
                "current_line_count": 10,
                "remaining_headroom": 340,
                "at_or_over_limit": False,
                "limit": 350,
                "classification": "authored",
            }], "no_changes": False},
        )
    )
    assert recorded.primary_success is True
    _force_lane_policy(monkeypatch)
    blocked = activation.evaluate_work_claim_activation(
        item_id=item_id,
        target_status="implementing",
        db_path="unused",
        session_id="session",
        conn=test_db,
    )
    assert blocked is not None
    assert blocked["error_code"] == "GATE_WORK_CLAIM_ACTIVATION_UNSATISFIED"
    assert "worktree" in blocked["error"].lower()
