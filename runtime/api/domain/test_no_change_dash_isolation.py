"""No-change Dash skips git isolation and restores it before edits."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

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
from yoke_core.domain import worktree_create
from yoke_core.domain import worktree_preflight as wp
from yoke_core.domain import worktree_preflight_upstream as upstream
from yoke_core.domain.handlers.direct_workflow_execution import handle_dash_survey
from yoke_core.domain.repo_upstream_freshness import STATE_CURRENT, UpstreamFreshness
from yoke_core.domain.workflow_behavior import WorktreeLanePolicy
from yoke_core.domain.worktree_preflight_repo_resolution import PreflightLaneTarget

_LANE_REQUIRED = WorktreeLanePolicy(
    allowed_roles=frozenset({"implementation"}),
    required_roles=frozenset({"implementation"}),
)
_ITEM = {
    "id": 7102,
    "public_ref": "YOK-7102",
    "workflow": {
        "id": "dash",
        "policies": {"worktrees": "single_implementation_lane"},
    },
    "project": {"slug": "yoke", "default_branch": "main"},
}


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


def _ok(function_id: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=function_id, version="v1", result=result
    )


def _install_real_prepare(monkeypatch, *, no_changes: bool) -> dict:
    """Drive the real preflight; explode git/create on a no-change survey."""
    captured: dict = {"create": [], "git": []}

    def _dispatch(*, function_id, **_kwargs):
        if function_id == "items.detail.get":
            return _ok(function_id, {"item": _ITEM})
        if function_id == "direct_workflow.conflict_survey.status":
            return _ok(function_id, _survey_status(no_changes=no_changes))
        if function_id == "claims.work.holder_get":
            return _ok(function_id, {"holder": {"session_id": "session"}})
        if function_id == "claims.path.survey_ensure":
            return _ok(function_id, {})
        raise AssertionError(function_id)

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatch,
    )
    monkeypatch.setattr(
        wp, "resolve_item_branch_and_lane", lambda _id: ("YOK-7102", None)
    )
    monkeypatch.setattr(wp, "_normalize_repo_root", lambda candidate: candidate)
    monkeypatch.setattr(wp, "claim_work", lambda _id: (True, "(already owned)"))
    monkeypatch.setattr(wp, "activate_path_claims", lambda _id: (True, "", []))
    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight_repo_resolution.resolve_preflight_lane_target",
        lambda **_k: PreflightLaneTarget(
            repo_root="/tmp/yoke-no-change-repo", project_slug="yoke"
        ),
    )
    monkeypatch.setattr(
        wp,
        "evaluate_dirty_main_for_item",
        lambda *_a, **_k: SimpleNamespace(
            blocked=False,
            kind="",
            narrative="",
            needed_paths=(),
            source_root_prefixes=(),
            warning_note="",
        ),
    )

    def _create(**kwargs):
        captured["create"].append(kwargs)
        if no_changes:
            raise AssertionError("create_worktree must not run for a no-change survey")
        return worktree_create.CreateWorktreeResult(
            path="/tmp/yoke-no-change-repo/.worktrees/YOK-7102",
            branch="YOK-7102",
            created=True,
        )

    def _git(*_a, **_k):
        captured["git"].append(True)
        if no_changes:
            raise AssertionError("git fetch must not run for a no-change survey")
        return UpstreamFreshness(
            state=STATE_CURRENT,
            verified=True,
            local_branch_current=True,
            lane_base_is_current=True,
            lane_base_ref="main",
        )

    monkeypatch.setattr(worktree_create, "create_worktree", _create)
    monkeypatch.setattr(upstream, "refresh_base_branch", _git)
    return captured


def test_no_change_prepare_skips_the_git_lane(monkeypatch, capsys):
    captured = _install_real_prepare(monkeypatch, no_changes=True)

    assert preflight.run(["YOK-7102", "--workflow", "dash", "--json"]) == 0
    assert captured["create"] == []
    assert captured["git"] == []
    envelope = json.loads(capsys.readouterr().out)
    assert "worktree:skipped" in envelope["actions_taken"]
    assert any("no-change" in note for note in envelope["notes"])


def test_path_survey_prepare_still_creates_a_lane(monkeypatch, capsys):
    captured = _install_real_prepare(monkeypatch, no_changes=False)

    assert preflight.run(["YOK-7102", "--workflow", "dash", "--json"]) == 0
    assert captured["create"]
    assert captured["git"]
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
            {
                "paths": ["src/x.py"],
                "path_sizes": [
                    {
                        "path": "src/x.py",
                        "current_line_count": 10,
                        "remaining_headroom": 340,
                        "at_or_over_limit": False,
                        "limit": 350,
                        "classification": "authored",
                    }
                ],
                "no_changes": False,
            },
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
