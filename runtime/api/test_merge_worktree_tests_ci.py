"""Merge-gate CI verification routing selection tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import project_ci_workflow as ci_workflow
from yoke_core.engines import merge_worktree_tests, merge_worktree_tests_ci


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
