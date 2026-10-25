"""One CI run proves a merged commit from merge verification through delivery.

Merge verification dispatches the CI workflow on the item's lane branch. The
merge lands that exact commit on the gate branch, so start-for-item binds it,
reuses that run without a second dispatch, returns the same run when asked
again, and the deploy gate passes on the same proof. A release of another
project that ships this project's source without the merge refuses instead.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from runtime.api.fixtures.backlog_insert_support import ensure_project_id
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    release_repository,
    serve_repository,
)
from runtime.api.domain.test_github_actions_rest import _RESOLVED
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain.deployment_item_delivery_owner import CARRIER_IN_FLIGHT
from yoke_core.domain.deployment_run_create_write import CreatedRun
from yoke_core.domain.handlers.github_actions_check_ci import handle_check_ci
from yoke_core.domain.handlers.github_actions_workflow import handle_workflow_find_run
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.qa_case_ci_covering_run import ADOPTED, classify
from yoke_core.domain.qa_case_ci_lane import WorkflowRun
from yoke_core.engines import runs_start_for_item as composer

ITEM_ID = 9621
WORKFLOW = "platform-quick-verification.yml"


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="merge-proof-delivery"),
        target=TargetRef(kind="global"),
        payload={"project": "platform", "repo": _RESOLVED.repo, "workflow": WORKFLOW,
                 **payload},
    )


@pytest.fixture
def merged(test_db, tmp_path, monkeypatch):
    """A merged item whose lane run proves the commit now at the gate tip."""
    insert_item(test_db, id=ITEM_ID, project_sequence=ITEM_ID, workflow_id="dash",
                status="release", merged_at="2026-10-25T10:00:00Z")
    test_db.commit()
    ref = item_ref(test_db, ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_entry(test_db, item_id=ITEM_ID, branch=ref, target="main",
                 merge_sha=landing)
    test_db.commit()
    runs = [
        {"id": 40197513779, "run_number": 12, "event": "workflow_dispatch",
         "head_branch": ref, "head_sha": landing, "status": "completed",
         "conclusion": "success"},
        {"id": 40197513780, "run_number": 13, "event": "pull_request",
         "head_branch": ref, "head_sha": landing, "status": "completed",
         "conclusion": "failure"},
    ]

    def _get(path, *, query=None, token):
        query = query or {}
        if path.endswith("/commits"):
            return [{"sha": landing}]
        return {"workflow_runs": [r for r in runs
                                  if r["head_sha"] == query.get("head_sha")]}

    def _no_second_dispatch(*_args, **_kwargs):
        pytest.fail("the merged commit already has its own CI run")

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_get", _get)
    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post",
                        _no_second_dispatch)
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kwargs: _RESOLVED,
    )
    slug = test_db.execute("SELECT slug FROM projects WHERE id = 1").fetchone()[0]
    monkeypatch.setattr(composer, "_lookup_item_project_and_flow",
                        lambda *_a: (str(slug), "flow"))
    monkeypatch.setattr(composer, "cmd_resolve_target",
                        lambda *_a, **_k: ("persistent", None, ""))
    monkeypatch.setattr(tested, "ci_gate_target", lambda *_a: tested.CiGateTarget(
        str(slug), "flow", _RESOLVED.repo, WORKFLOW, "main", "t", ""))
    created: list[str] = []

    def _create(project, flow, item_id, **kwargs):
        created.append(kwargs["release_lineage"])
        insert_run(test_db, "run-delivery", lineage=kwargs["release_lineage"],
                   status="created", flow=flow)
        test_db.execute("INSERT INTO deployment_run_items(run_id,item_id,added_at) "
                        "VALUES ('run-delivery',%s,'2026-10-25T10:05:00Z')", (item_id,))
        test_db.commit()
        return CreatedRun("run-delivery", False, None), "OK"

    monkeypatch.setattr(composer, "create_item_run", _create)
    return {"ref": ref, "baseline": baseline, "landing": landing, "created": created}


def test_merge_proof_carries_the_identical_commit_through_delivery(merged):
    landing = merged["landing"]
    found = handle_workflow_find_run(
        _request("github_actions.workflow.find_run", {"head_sha": landing})
    ).result_payload
    run = WorkflowRun(run_id=found["run_id"], status=found["status"],
                      conclusion=found["conclusion"], html_url="", head_sha=landing)
    assert classify(run, head_sha=landing) == ADOPTED

    first = composer.start_for_item(ITEM_ID)
    assert (first.ok, first.reused, first.run_id) == (True, False, "run-delivery")
    assert merged["created"] == [landing]

    again = composer.start_for_item(ITEM_ID)
    assert (again.ok, again.reused, again.run_id) == (True, True, "run-delivery")
    assert merged["created"] == [landing]

    gate = handle_check_ci(
        _request("github_actions.check_ci", {"branch": "", "head_sha": landing})
    ).result_payload
    assert (gate["state"], gate["run_id"]) == ("passed", 40197513779)


def test_a_bound_release_missing_the_merge_refuses_before_creation(
    merged, test_db: Any, monkeypatch
):
    from yoke_core.domain.project_github_auth_models import ProjectGithubAuthError

    def _no_provider(project, **_kwargs):
        raise ProjectGithubAuthError(project, "containment reads the checkout here")

    # The refusal comes before any source binding, so only the checkout
    # answers containment.
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth", _no_provider
    )
    carrier = ensure_project_id(test_db, "carrier", ts=datetime.now(timezone.utc))
    pinned = merged["baseline"]
    insert_run(test_db, "run-carrier", lineage="e" * 40, status="executing",
               flow="carrier-release", project_id=carrier,
               bound_sources=json.dumps({"schema": 1, "projects": [
                   {"project_id": 1, "commit_sha": pinned}]}))

    refused = composer.start_for_item(ITEM_ID)

    assert (refused.ok, refused.error_code, refused.run_id) == (
        False, CARRIER_IN_FLIGHT, "run-carrier")
    assert f"its pinned commit {pinned} does not contain" in refused.error
    assert merged["created"] == []
