"""Merge-gate CI verification: routing selection, and reusing a live run."""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import project_ci_workflow as ci_workflow
from yoke_core.domain import (
    qa_case_ci_covering_run as covering_run,
    qa_case_ci_lane,
    verification_tree_binding,
)
from yoke_core.engines import merge_worktree_tests, merge_worktree_tests_ci

CANDIDATE = "e" * 40


def _ctx(tmp_path, *, project="yoke", item_id="42", local_verification=False):
    return SimpleNamespace(
        project=project,
        item_id=item_id,
        worktree_path=str(tmp_path),
        args=SimpleNamespace(
            branch="YOK-42",
            local_verification=local_verification,
        ),
    )


def _resolved(scope, command, covering_runs=()):
    return lambda _ctx: (scope, command, list(covering_runs))


def test_should_route_ci_respects_local_override(monkeypatch):
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "project_ci_workflow_file",
        lambda _p: "ci.yml",
    )
    ctx = _ctx("/tmp", local_verification=True)
    assert merge_worktree_tests_ci._should_route_ci(ctx) is False
    ctx.args.local_verification = False
    assert merge_worktree_tests_ci._should_route_ci(ctx) is True


def test_ci_workflow_read_uses_connected_capability_surface(monkeypatch):
    seen = []

    def fake_dispatch(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            success=True,
            result={"settings_json": '{"workflow_file":"ci.yml"}'},
            error=None,
        )

    monkeypatch.setattr(ci_workflow, "call_dispatcher", fake_dispatch)

    assert ci_workflow.project_ci_workflow_file("yoke") == "ci.yml"
    assert seen[0]["function_id"] == "projects.capability_settings.get"
    assert seen[0]["target"].kind == "global"
    assert seen[0]["payload"] == {
        "project": "yoke",
        "cap_type": "ci_workflow_file",
    }


def test_ci_workflow_read_treats_missing_capability_as_undeclared(monkeypatch):
    monkeypatch.setattr(
        ci_workflow,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=False,
            result=None,
            error=SimpleNamespace(code="not_found", message="missing"),
        ),
    )

    assert ci_workflow.project_ci_workflow_file("yoke") == ""


def test_run_tests_routes_to_ci_when_declared(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved("full", "python3 verify_tree.py"),
    )
    called = []

    def fake_ci(ctx, *, scope, command):
        called.append((scope, command, ctx.item_id))
        return None

    monkeypatch.setattr(
        merge_worktree_tests,
        "_run_streaming",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("local streaming must not run when CI routes")
        ),
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tests_ci.run_ci_verification",
        fake_ci,
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tests_ci._should_route_ci",
        lambda _ctx: True,
    )
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) is None
    assert called == [("full", "python3 verify_tree.py", "42")]


def test_run_tests_keeps_local_when_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved("quick", "python3 verify_tree.py"),
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tests_ci._should_route_ci",
        lambda _ctx: False,
    )
    seen = []
    monkeypatch.setattr(
        merge_worktree_tests,
        "_run_streaming",
        lambda command, **kwargs: (seen.append(command), (0, "ok"))[1],
    )
    assert (
        merge_worktree_tests.run_tests(_ctx(tmp_path, local_verification=True)) is None
    )
    assert seen == [["/bin/sh", "-c", "python3 verify_tree.py"]]


def test_parse_args_local_verification():
    from yoke_core.engines.merge_worktree import parse_args

    args = parse_args(["YOK-1", "main", "--local-verification"])
    assert args.local_verification is True
    assert args.branch == "YOK-1"


@pytest.fixture()
def ci_gate(tmp_path, monkeypatch):
    """Stub every boundary ``run_ci_verification`` crosses; return the evidence."""
    recorded: list[dict] = []
    monkeypatch.setattr(
        merge_worktree_tests_ci, "project_ci_workflow_file", lambda _p: "ci.yml",
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_parent",
        lambda: SimpleNamespace(_print=lambda *a, **k: print(*a)),
    )
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_tree_identity",
        lambda tree: verification_tree_binding.TreeIdentity(str(tree), CANDIDATE),
    )
    monkeypatch.setattr(qa_case_ci_lane, "repo_slug", lambda _c: "acme/widgets")
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", lambda *a, **k: None)
    monkeypatch.setattr(
        qa_case_ci_lane, "github_actions_authority", contextlib.nullcontext,
    )
    monkeypatch.setattr(qa_case_ci_lane, "run_head_sha", lambda **k: "")
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "call_dispatcher",
        lambda **kwargs: (
            recorded.append(kwargs["payload"]),
            SimpleNamespace(success=True, result={"qa_run_id": 5}, error=None),
        )[1],
    )
    return _ctx(tmp_path), recorded


def _completed(conclusion="success"):
    return qa_case_ci_lane.WorkflowRun(
        "77", "completed", conclusion, "https://github.test/runs/77", CANDIDATE,
    )


def test_a_concluded_run_on_the_candidate_is_adopted_without_a_second_suite(
    ci_gate, monkeypatch,
):
    ctx, recorded = ci_gate
    monkeypatch.setattr(
        covering_run, "find_run_for_tree", lambda **k: _completed(),
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "dispatch_workflow",
        mock.Mock(side_effect=AssertionError("must not dispatch")),
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "await_workflow",
        mock.Mock(side_effect=AssertionError("must not await a concluded run")),
    )

    assert merge_worktree_tests_ci.run_ci_verification(
        ctx, scope="full", command="python3 -m pytest",
    ) is None

    evidence = json.loads(recorded[0]["raw_result"])
    assert recorded[0]["verdict"] == "pass"
    assert evidence["ci_run_source"] == covering_run.ADOPTED
    assert evidence["ci_run_id"] == "77"
    assert evidence["ci_conclusion"] == "success"


def test_an_adopted_red_run_reports_its_own_conclusion_not_an_error(
    ci_gate, monkeypatch,
):
    """A polled failure is read out of poll text; an adopted one is already known."""
    ctx, recorded = ci_gate
    monkeypatch.setattr(
        covering_run, "find_run_for_tree", lambda **k: _completed("failure"),
    )

    result = merge_worktree_tests_ci.run_ci_verification(
        ctx, scope="full", command="python3 -m pytest",
    )

    assert result == (1, "tests failed")
    evidence = json.loads(recorded[0]["raw_result"])
    assert recorded[0]["verdict"] == "fail"
    assert evidence["ci_conclusion"] == "failure"


def test_a_run_still_in_flight_on_the_candidate_is_attached_to(ci_gate, monkeypatch):
    ctx, recorded = ci_gate
    monkeypatch.setattr(
        covering_run,
        "find_run_for_tree",
        lambda **k: qa_case_ci_lane.WorkflowRun(
            "88", "in_progress", "", "https://github.test/runs/88", CANDIDATE,
        ),
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "dispatch_workflow",
        mock.Mock(side_effect=AssertionError("must not dispatch")),
    )
    awaited: list[str] = []
    monkeypatch.setattr(
        qa_case_ci_lane,
        "await_workflow",
        lambda **k: (awaited.append(k["run_id"]), (0, "success"))[1],
    )

    assert merge_worktree_tests_ci.run_ci_verification(
        ctx, scope="full", command="python3 -m pytest",
    ) is None

    assert awaited == ["88"]
    assert json.loads(recorded[0]["raw_result"])["ci_run_source"] == (
        covering_run.ATTACHED
    )


def test_an_unexamined_candidate_still_dispatches(ci_gate, monkeypatch):
    ctx, recorded = ci_gate
    monkeypatch.setattr(covering_run, "find_run_for_tree", lambda **k: None)
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", lambda **k: "99")
    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"))

    assert merge_worktree_tests_ci.run_ci_verification(
        ctx, scope="full", command="python3 -m pytest",
    ) is None

    evidence = json.loads(recorded[0]["raw_result"])
    assert evidence["ci_run_source"] == covering_run.DISPATCHED
    assert evidence["ci_run_id"] == "99"
