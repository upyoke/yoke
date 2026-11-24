"""The candidate-consuming commands reconcile the lane they selected."""

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain import (
    deploy_pipeline_control_plane as deploy,
    deployment_lane_heads,
    lane_head_client,
    lane_head_record,
    qa_case_execution,
    qa_case_stage_credit,
    qa_lane_head,
    standalone_item_merge_lane,
)
from yoke_core.domain.merge_context import MergeArgs
from yoke_core.engines import done_transition_item_context, done_transition_preconditions
from yoke_core.engines.merge_worktree_recorded_source import reconcile_epic_source

OLD = "a" * 40
NEW = "b" * 40


@pytest.fixture
def lanes():
    return [
        {"id": 1, "path": "/fixture/integration", "branch": "integration",
         "commit_sha": "c" * 40, "lane_role": "integration"},
        {"id": 2, "path": "/fixture/worker", "branch": "worker",
         "commit_sha": OLD, "lane_role": "worker"},
    ]


def test_case_reads_new_record_without_overwriting_explicit_sha(monkeypatch, lanes):
    lane = lanes[1]
    case = {
        "project": "fixture", "lane_id": lane["id"], "lane_path": lane["path"],
        "lane_commit_sha": OLD, "lane_branch": lane["branch"],
    }
    fresh = {**case, "lane_commit_sha": NEW}
    events = []
    actor = ActorContext(session_id="review-session")

    def fetch(requirement, **selection):
        events.append(("read", requirement, selection["checkout_path"]))
        return fresh if len(events) > 1 else case

    def reconcile(project, selected, **options):
        events.append(("write", project, selected["path"], options["session_id"]))
        return NEW, ""

    monkeypatch.setattr(qa_case_execution, "fetch_case_execution_context", fetch)
    monkeypatch.setattr(qa_lane_head, "reconcile_lane_head", reconcile)
    monkeypatch.setattr(
        qa_case_execution, "execute_case_context",
        lambda selected, **kwargs: (selected, kwargs["expected_sha"]),
    )
    assert qa_case_stage_credit.execute_authorized_case(
        7, actor=actor, checkout_path=lane["path"],
        expected_branch=lane["branch"], expected_sha=OLD,
    ) == (fresh, OLD)
    assert events == [
        ("read", 7, lane["path"]),
        ("write", "fixture", lane["path"], actor.session_id),
        ("read", 7, lane["path"]),
    ]


def test_plan_refreshes_selected_case_lane(monkeypatch, lanes):
    lane = lanes[1]
    actor = ActorContext(session_id="plan-session")
    target = TargetRef(kind="item", public_ref="ITEM-9")
    seen = []
    case = {"lane_id": lane["id"], "lane_path": lane["path"]}

    def fetch(requirement, **selectors):
        assert selectors["checkout_path"] == lane["path"]
        seen.append(requirement)
        return case

    monkeypatch.setattr(qa_case_execution, "fetch_case_execution_context", fetch)
    monkeypatch.setattr(qa_lane_head, "reconcile_case_lane", lambda selected, _: seen.append(selected))
    qa_lane_head.reconcile_plan_lanes(
        target, transition_id="review", requirement_id=None,
        checkout_path=lane["path"], expected_branch=lane["branch"], actor=actor,
        call=lambda **kwargs: {"rows": [
            {"id": 8, "workflow_transition_id": "later", "runner_id": "worktree_run"},
            {"id": 7, "workflow_transition_id": "review", "runner_id": "ci_run"},
        ]},
    )
    assert seen == [7, case]


@pytest.mark.parametrize("operation, selected", [("review", 1), ("done", 0)])
def test_item_operations_reconcile_only_selected_lane(monkeypatch, lanes, operation, selected):
    calls = []
    monkeypatch.setattr(lane_head_client, "read_item_lanes", lambda *a, **k: ("fixture", lanes))
    monkeypatch.setattr(
        lane_head_client, "reconcile_lane_head",
        lambda project, lane, **kwargs: (calls.append(lane["id"]) or NEW, ""),
    )
    if operation == "review":
        task = TargetRef(kind="epic_task", public_ref="ITEM-9", task_num=3)

        def dispatch(**kwargs):
            assert kwargs["target"] == task
            assert kwargs["function_id"] == "workflow_item.epic_task.get"
            return SimpleNamespace(success=True, result={"worktree_id": lanes[1]["id"]})

        monkeypatch.setattr(lane_head_client, "get_structured_dispatch", lambda: SimpleNamespace(
            build_actor=lambda **kwargs: ActorContext(**kwargs), call_dispatcher=dispatch,
        ))
        lane_head_client.reconcile_task_lane(task, session_id="tester")
    else:
        context = SimpleNamespace(lane_branch=lanes[0]["branch"])
        monkeypatch.setattr(done_transition_item_context, "load_done_item_context_over_transport",
                            lambda ref: context)
        assert done_transition_preconditions.load_done_context_with_current_lane("ITEM-9") is context
    assert calls == [lanes[selected]["id"]]


def test_epic_merge_binds_requested_branch_after_refresh(monkeypatch, lanes):
    args = MergeArgs(branch=lanes[1]["branch"], source_sha=OLD)
    epic = {"project": {"slug": "fixture"}, "worktrees": lanes}

    def reconcile(project, lane):
        assert project == "fixture"
        assert lane is lanes[1]
        return NEW, ""

    monkeypatch.setattr(lane_head_record, "reconcile_lane_head", reconcile)
    reconcile_epic_source(args, epic)
    assert args.source_sha == NEW


@pytest.mark.parametrize("operation", ["context", "executing", "succeeded"])
def test_deploy_driver_refreshes_member_without_rewriting_run_pin(monkeypatch, lanes, operation):
    events = []
    monkeypatch.setattr(deploy, "current_member_refs", lambda run_id: ["ITEM-9"])
    monkeypatch.setattr(deployment_lane_heads, "read_item_lanes", lambda *a: ("fixture", lanes))
    monkeypatch.setattr(deployment_lane_heads, "reconcile_lane_head",
                        lambda project, lane: (events.append(lane["id"]) or NEW, ""))
    monkeypatch.setattr(deploy, "_call",
                        lambda function, run_id, payload: events.append(payload) or {"updated": True})
    if operation == "context":
        deploy.execution_context("run-fixture")
        assert events == [lanes[1]["id"], {}]
    else:
        deploy.update_run_field("run-fixture", "status", operation)
        assert events == [lanes[1]["id"], {"field": "status", "value": operation}]


def test_read_only_merge_reports_stale_queued_lane(monkeypatch, lanes):
    item = {"worktrees": lanes, "merge_queue": {"head_sha": OLD}}

    def inspect(lane):
        assert lane is lanes[1]
        return NEW, ""

    monkeypatch.setattr(lane_head_record, "local_lane_head", inspect)
    monkeypatch.setattr(lane_head_record, "record_lane_head", lambda *a: pytest.fail("write"))
    assert standalone_item_merge_lane.stale_head_note(item) == (
        f"lane head stale: lane at {NEW}, record at {OLD}; the merge will record the lane head"
    )
    assert lanes[1]["commit_sha"] == OLD
