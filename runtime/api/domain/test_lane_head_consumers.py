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


def test_released_case_preserves_its_candidate(monkeypatch, lanes):
    lane = lanes[1]
    monkeypatch.setattr(qa_lane_head, "reconcile_lane_head", lambda *a, **k: pytest.fail("write"))
    assert qa_lane_head.reconcile_case_lane(
        {"lane_id": lane["id"], "lane_path": lane["path"], "lane_state": "released"},
        None,
    ) == ""


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
        context = SimpleNamespace(project="fixture", lane=lanes[0])
        monkeypatch.setattr(
            lane_head_record, "reconcile_lane_head",
            lambda project, lane: (calls.append(lane["id"]) or NEW, ""),
        )
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
    with deployment_lane_heads.deployment_lane_head_scope("run-fixture"):
        if operation == "context":
            deploy.execution_context("run-fixture")
            assert events == [lanes[1]["id"], {}]
        else:
            deploy.update_run_field("run-fixture", "status", operation)
            assert events == [lanes[1]["id"], {"field": "status", "value": operation}]


def test_deploy_driver_refreshes_before_qa_failure_handoff(monkeypatch):
    from yoke_core.domain import deployment_qa_stage_dispatch as qa_dispatch
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch

    events = []
    run_id = "run-fixture"
    monkeypatch.setattr(
        deployment_lane_heads, "reconcile_member_lanes",
        lambda selected_run: events.append(("reconcile", selected_run)),
    )

    def dispatch(**kwargs):
        events.append(("dispatch", kwargs["target"].workflow_run_id))
        return SimpleNamespace(success=True, result={"code": 0})

    monkeypatch.setattr(get_structured_dispatch(), "call_dispatcher", dispatch)
    assert qa_dispatch.dispatch_deployment_qa_stage({"name": "item-qa"}, run_id=run_id) == (0, "")
    assert events == [("reconcile", run_id), ("dispatch", run_id)]


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
    assert standalone_item_merge_lane.stale_head_note(item, as_json=False) == (
        f"record the stale lane head (lane at {NEW}, record at {OLD})"
    )
    assert lanes[1]["commit_sha"] == OLD


def test_hook_free_deploy_execute_reconciles_each_phase_and_preserves_run_pin(tmp_path, monkeypatch):
    """Exercise the actual execute ports against an isolated transport ledger."""
    import subprocess

    from yoke_cli.commands.adapters import project_snapshot
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
    from yoke_core.domain import (
        deploy_pipeline_run_context,
        deploy_pipeline_run_updates,
        deployment_qa_stage_dispatch as stage,
    )

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def advance(message):
        git("commit", "--allow-empty", "-m", message)
        return git("rev-parse", "HEAD")

    git("init", "-b", "lane")
    git("config", "user.email", "lane@example.org")
    git("config", "user.name", "Lane")
    git("config", "core.hooksPath", str(tmp_path / "disabled-hooks"))
    pinned = advance("frozen release")
    sibling = {
        "id": 1, "path": str(tmp_path / "sibling"), "branch": "sibling",
        "commit_sha": pinned, "state": "active",
    }
    selected = {
        "id": 2, "path": str(tmp_path), "branch": "lane",
        "commit_sha": pinned, "state": "active",
    }
    run = {"id": "run-fixture", "release_lineage": pinned, "status": "created"}
    consumed = []
    writes = []

    def dispatch(*, function_id, target, payload, **kwargs):
        if function_id == "deployment_runs.get":
            assert target.workflow_run_id == run["id"]
            assert payload == {"field": "member_items"}
            result = {"value": [{"ref": "ITEM-9"}]}
        elif function_id == "items.detail.get":
            assert target.public_ref == "ITEM-9"
            result = {"item": {
                "project": {"slug": "fixture"}, "worktrees": [dict(sibling), dict(selected)],
            }}
        elif function_id == "project.snapshot.sync":
            assert target.project_id == "fixture"
            assert payload["repo_root"] == str(tmp_path)
            head = payload["snapshots"][0]["commit_sha"]
            selected["commit_sha"] = head
            writes.append(head)
            result = {"snapshots": [{"ref": "HEAD", "commit_sha": head, "lane_head_recorded": True}]}
        else:
            assert target.workflow_run_id == run["id"]
            consumed.append((function_id, selected["commit_sha"], run["release_lineage"]))
            if function_id == "deployment_runs.execution.context":
                result = {"run": dict(run)}
            elif function_id == "deployment_runs.execution.update":
                assert payload["field"] == "status"
                assert "release_lineage" not in payload
                run["status"] = payload["value"]
                result = {"updated": True}
            elif function_id == stage.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION:
                assert payload == {"stage_name": "item-qa"}
                result = {"code": -4, "message": "failed QA awaits handoff", "pending_plans": []}
            else:
                pytest.fail(f"unexpected transport call: {function_id}")
        return FunctionCallResponse(
            success=True, function=function_id, version="v1", result=result,
        )

    monkeypatch.setattr(deploy, "call_dispatcher", dispatch)
    monkeypatch.setattr(get_structured_dispatch(), "call_dispatcher", dispatch)
    monkeypatch.setattr(lane_head_record, "required_project", lambda project, **kw: project)
    monkeypatch.setattr(project_snapshot, "_project_context", lambda project: project)
    monkeypatch.setattr(project_snapshot, "assert_project_repository", lambda *a, **kw: None)
    monkeypatch.setattr(project_snapshot, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(project_snapshot, "call_dispatcher", dispatch)

    with deployment_lane_heads.deployment_lane_head_scope(run["id"]):
        start = advance("external commit before start")
        assert deploy.execution_context(run["id"])["run"]["release_lineage"] == pinned
        deploy_pipeline_run_updates.start_run(run["id"], None, str(tmp_path))
        git("reset", "--hard", pinned)
        assert deploy.execution_context(run["id"])["run"]["status"] == "executing"
        handoff = advance("external commit before QA handoff")
        assert stage.dispatch_deployment_qa_stage(
            {"name": "item-qa"}, run_id=run["id"],
        ) == (-4, "failed QA awaits handoff")
        finish = advance("external commit before settlement")
        deploy_pipeline_run_context._update_run_succeeded(run["id"], None)

    assert writes == [start, pinned, handoff, finish]
    assert consumed == [
        ("deployment_runs.execution.context", start, pinned),
        ("deployment_runs.execution.update", start, pinned),
        ("deployment_runs.execution.context", pinned, pinned),
        (stage.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION, handoff, pinned),
        ("deployment_runs.execution.update", finish, pinned),
    ]
    assert run["status"] == "succeeded"
    assert run["release_lineage"] == sibling["commit_sha"] == pinned


def test_typed_done_refreshes_a_stale_selected_lane_before_transition(monkeypatch, lanes):
    from yoke_cli.commands.adapters import lifecycle_transition as cli

    lane = lanes[0]
    assert lane is not lanes[1]
    calls = []

    def dispatch(**kwargs):
        assert kwargs["function_id"] == "done_transition.item_context"
        assert kwargs["target"].public_ref == "ITEM-9"
        calls.append("context")
        return SimpleNamespace(
            success=True,
            result={"stage_id": "release", "project": "fixture", "lane": lane},
        )

    def reconcile(project, selected, **kwargs):
        assert project == "fixture"
        assert selected is lane
        calls.append("snapshot")
        return NEW, ""

    def transition(**kwargs):
        calls.append("transition")
        assert kwargs["function_id"] == "lifecycle.transition.execute"
        assert kwargs["payload"]["target_status"] == "done"
        return 0

    monkeypatch.setattr(lane_head_client, "get_structured_dispatch", lambda: SimpleNamespace(
        build_actor=lambda session_id: ActorContext(session_id=session_id or "fixture"),
        call_dispatcher=dispatch,
    ))
    monkeypatch.setattr(lane_head_client, "reconcile_lane_head", reconcile)
    monkeypatch.setattr(cli, "dispatch_and_emit", transition)
    assert cli.lifecycle_transition(["ITEM-9", "--from", "release", "--to", "done"]) == 0
    assert calls == ["context", "snapshot", "transition"]
