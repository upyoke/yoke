"""Survey-versus-claim contacts advise; claim-versus-claim still blocks."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    seed_item_claim,
    seed_target,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import direct_workflow_worktree_preflight as preflight
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.dash_path_claim_posture import ensure_survey_path_claim
from yoke_core.domain.path_claims import IncompatibleOverlap, register
from yoke_core.domain.path_claims_overlap_survey import (
    SURVEY_ADVISORY_PROCEED,
    SURVEY_ADVISORY_YIELD,
)

SHARED = "src/shared.py"


def test_survey_yield_route_uses_survey_native_actions():
    for required in (
        "wait for the holding work to finish",
        "re-run the survey",
        "release the work claim",
        "present the overlapping path, holder, and evidence to the operator",
        "do not continue editing",
    ):
        assert required in SURVEY_ADVISORY_YIELD
    for path_claim_remedy in (
        "activation dependency",
        "coordination_only",
        "coordinate",
        "register",
        "widen",
    ):
        assert path_claim_remedy not in SURVEY_ADVISORY_YIELD


@pytest.fixture(autouse=True)
def _no_render_target_context(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_path_context.read_render_source_for",
        lambda *_args, **_kwargs: None,
    )


def _resp(function: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=function,
        version="v1",
        result=result,
        error=None,
    )


class _AdvisoryDispatcher:
    def __init__(self, *, item: dict, owner: dict, status_result: dict):
        self.item = item
        self.owner = owner
        self.status_result = status_result

    def __call__(self, *, function_id: str, target, **_kwargs):
        if function_id == "items.detail.get":
            row = (
                self.owner
                if getattr(target, "item_id", None) == self.owner["id"]
                else self.item
            )
            return _resp(function_id, {"item": row})
        if function_id == "direct_workflow.conflict_survey.status":
            return _resp(function_id, self.status_result)
        raise AssertionError(f"unexpected function id {function_id!r}")


def test_path_claim_survey_contact_advises_and_prepares(monkeypatch, capsys):
    owner = {
        "id": 4200,
        "public_ref": "YOK-4200",
        "status": "implementing",
        "workflow": {"id": "issue"},
    }
    item = {"id": 4103, "workflow": {"id": "dash"}}
    dispatcher = _AdvisoryDispatcher(
        item=item,
        owner=owner,
        status_result={
            "found": True,
            "clear": False,
            "touch_paths": [SHARED],
            "integration_target": "main",
            "blockers": [
                {
                    "kind": "path_claim",
                    "owner_item_id": 4200,
                    "path": SHARED,
                    "state": "active",
                },
                {
                    "kind": "work_claim",
                    "owner_item_id": 4200,
                    "path": SHARED,
                    "state": "active",
                },
            ],
        },
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        dispatcher,
    )
    monkeypatch.setattr(preflight, "connect", lambda *_a, **_k: None, raising=False)
    preflight_calls: list[dict] = []

    def _fake_run_preflight(**kwargs):
        preflight_calls.append(kwargs)
        return type("Outcome", (), {"ok": True, "to_envelope": lambda self: {}})()

    monkeypatch.setattr(preflight, "run_preflight", _fake_run_preflight)

    rc = preflight.run(["YOK-4103", "--workflow", "dash"])

    assert rc == 0
    assert len(preflight_calls) == 1
    emitted = json.loads(capsys.readouterr().out.strip())
    assert "block_kind" not in emitted
    by_kind = {row["kind"]: row for row in emitted["advisories"]}
    assert set(by_kind) == {"path_claim", "work_claim"}
    for advisory in by_kind.values():
        assert advisory["item_ref"] == "YOK-4200"
        assert advisory["status"] == "implementing"
        assert advisory["shared_paths"] == [SHARED]
        assert advisory["routes"]["proceed"] == SURVEY_ADVISORY_PROCEED
        assert advisory["routes"]["yield"] == SURVEY_ADVISORY_YIELD


def test_two_claims_on_one_file_stay_incompatible(test_db):
    insert_item(test_db, id=2290, workflow_id="issue")
    insert_item(test_db, id=2291, workflow_id="issue")
    target_id = seed_target(test_db, item_id=2290, path=SHARED)
    seed_item_claim(
        test_db,
        item_id=2290,
        target_ids=(target_id,),
        state="active",
    )
    with pytest.raises(IncompatibleOverlap, match="active claim"):
        register(
            test_db,
            actor_id=seed_human_actor(test_db),
            integration_target="main",
            target_ids=[target_id],
            item_id=2291,
            candidate_item_id=2291,
        )


def test_incomplete_coverage_refuses_without_widening(test_db):
    insert_item(
        test_db,
        id=2292,
        workflow_id="dash",
        workflow_posture=json.dumps({"path_claims": True}),
    )
    target_id = seed_target(test_db, item_id=2292, path="src/a.py")
    claim_id = seed_item_claim(
        test_db,
        item_id=2292,
        target_ids=(target_id,),
        state="planned",
    )
    with pytest.raises(ValueError, match="yoke claims path widen --claim-id"):
        ensure_survey_path_claim(
            test_db,
            item_id=2292,
            session_id="s",
            touch_paths=["src/a.py", "src/b.py"],
            integration_target="main",
        )
    declared = test_db.execute(
        "SELECT pt.path_string FROM path_claim_targets pct "
        "JOIN path_targets pt ON pt.id = pct.target_id "
        "WHERE pct.claim_id = %s",
        (claim_id,),
    ).fetchall()
    assert [row[0] for row in declared] == ["src/a.py"]
