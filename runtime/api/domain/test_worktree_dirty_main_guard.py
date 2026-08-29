"""Scoped dirty-main guard: overlap, needed paths, and holder narrative."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import worktree_dirty_main_guard as guard
from yoke_core.domain.worktree_create_plan import dirty_main_error
from yoke_core.domain.worktree_preflight_steps import (
    BLOCK_DIRTY_TRACKED,
    BLOCK_DIRTY_UNTRACKED,
)


def _fake_run(canned):
    queue = list(canned)

    def _run(cmd, *_args, **_kwargs):
        if not queue:
            raise AssertionError(f"unexpected _run call: {cmd!r}")
        rc, out, err = queue.pop(0)
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    return _run


def _resp(function, *, result=None, success=True):
    return FunctionCallResponse(
        success=success,
        function=function,
        version="v1",
        result=result or {},
    )


def _patch_dispatch(monkeypatch, router):
    from yoke_core.api import service_client_structured_api_adapter as facade

    monkeypatch.setattr(facade, "call_dispatcher", router)


def _git_tracked(path: str):
    return [(0, f"{path}\n", ""), (0, "", ""), (0, "", "")]


def _git_untracked(path: str):
    return [(0, "", ""), (0, "", ""), (0, f"{path}\n", "")]


def test_empty_needed_paths_do_not_block_tracked_dirt(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))
    blocked, kind, paths = guard.overlapping_dirty_main("/repo")
    assert (blocked, kind, paths) == (False, "", ())


def test_unrelated_tracked_dirt_does_not_block(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))
    blocked, kind, paths = guard.overlapping_dirty_main(
        "/repo", ["runtime/api/other.py"]
    )
    assert (blocked, kind, paths) == (False, "", ())


def test_directory_scope_overlap_blocks_tracked(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("runtime/api/foo.py")))
    blocked, kind, paths = guard.overlapping_dirty_main("/repo", ["runtime/api"])
    assert blocked is True
    assert kind == BLOCK_DIRTY_TRACKED
    assert paths == ("runtime/api/foo.py",)


def test_overlapping_untracked_does_not_block_repo_root_scratch(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_untracked("scratch.txt")))
    blocked, kind, paths = guard.overlapping_dirty_main("/repo", ["scratch.txt"])
    assert (blocked, kind, paths) == (False, "", ())


def test_nested_untracked_blocks_without_needed_paths(monkeypatch):
    monkeypatch.setattr(
        guard, "_run", _fake_run(_git_untracked("packages/yoke_core/new.py"))
    )
    blocked, kind, paths = guard.overlapping_dirty_main("/repo")
    assert blocked is True
    assert kind == BLOCK_DIRTY_UNTRACKED
    assert paths == ("packages/yoke_core/new.py",)


def test_untracked_under_worktrees_dir_is_exempt(monkeypatch):
    monkeypatch.setattr(
        guard,
        "_run",
        _fake_run(_git_untracked(".worktrees/YOK-1/tmp.py")),
    )
    blocked, kind, paths = guard.overlapping_dirty_main(
        "/repo",
        [".worktrees/YOK-1/tmp.py"],
        worktrees_dir="/repo/.worktrees",
    )
    assert (blocked, kind, paths) == (False, "", ())


def test_dirty_main_error_is_none_without_needed_paths(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))
    assert dirty_main_error("/repo", "/repo/.worktrees") is None


def test_dirty_main_error_names_overlap(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))
    message = dirty_main_error("/repo", "/repo/.worktrees", ["foo.py"])
    assert message is not None
    assert "overlapping" in message
    assert "foo.py" in message


def test_lane_needed_paths_unions_survey_claims_and_budget(monkeypatch):
    def router(*, function_id, target, payload=None, **_k):
        if function_id == "direct_workflow.conflict_survey.status":
            return _resp(function_id, result={"touch_paths": ["a/one.py"]})
        if function_id == "claims.path.list":
            return _resp(
                function_id,
                result={"claims": [{"declared_paths": ["b/two.py"]}]},
            )
        if function_id == "items.section.get":
            return _resp(
                function_id,
                result={"content": "- `c/three.py` owns the budget path\n"},
            )
        raise AssertionError(function_id)

    _patch_dispatch(monkeypatch, router)
    assert guard.lane_needed_paths(42) == ("a/one.py", "b/two.py", "c/three.py")


def test_holders_prefer_main_lane_on_same_machine(monkeypatch):
    def router(*, function_id, target, payload=None, **_k):
        assert function_id == "sessions.list"
        return _resp(
            function_id,
            result={
                "rows": [
                    {
                        "session_id": "caller",
                        "machine_id": "m1",
                        "work_role": "item",
                        "actor_label": "me",
                    },
                    {
                        "session_id": "holder",
                        "machine_id": "m1",
                        "work_role": "item",
                        "actor_label": "ben",
                        "current_item": "YOK-9",
                        "claims": [{"lane_role": None}],
                    },
                    {
                        "session_id": "other-machine",
                        "machine_id": "m2",
                        "work_role": "item",
                        "actor_label": "skip",
                    },
                    {
                        "session_id": "worker",
                        "machine_id": "m1",
                        "work_role": "worker",
                        "claims": [{"lane_role": "worker"}],
                    },
                ]
            },
        )

    _patch_dispatch(monkeypatch, router)
    holders = guard.list_main_lane_holders(caller_session_id="caller")
    assert [row["session_id"] for row in holders] == ["holder"]
    assert holders[0]["current_item"] == "YOK-9"


def test_narrative_includes_session_id_and_say_recipe(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))

    def router(*, function_id, target, payload=None, **_k):
        return _resp(
            function_id,
            result={
                "rows": [
                    {
                        "session_id": "caller",
                        "machine_id": "m1",
                        "work_role": "item",
                    },
                    {
                        "session_id": "abc-123",
                        "machine_id": "m1",
                        "work_role": "item",
                        "actor_label": "ben",
                        "current_item": "YOK-9",
                    },
                ]
            },
        )

    _patch_dispatch(monkeypatch, router)
    verdict = guard.evaluate_dirty_main_for_item(
        "/repo",
        item_id=1,
        public_ref="YOK-1",
        session_id="caller",
        needed_paths=("foo.py",),
    )
    assert verdict.blocked is True
    assert verdict.kind == BLOCK_DIRTY_TRACKED
    assert "abc-123" in verdict.narrative
    # The holder's item addresses them; the session id stays as identity.
    assert "yoke say --preview --item YOK-9" in verdict.narrative
    assert "yoke say --item YOK-9 --stdin" in verdict.narrative
    assert "foo.py" in verdict.narrative


def test_narrative_falls_back_to_the_session_when_no_item_names_the_holder(
    monkeypatch,
):
    """A holder with no current item has no address but its own id."""
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))

    def router(*, function_id, target, payload=None, **_k):
        return _resp(
            function_id,
            result={
                "rows": [
                    {
                        "session_id": "caller",
                        "machine_id": "m1",
                        "work_role": "item",
                    },
                    {
                        "session_id": "abc-123",
                        "machine_id": "m1",
                        "work_role": "item",
                        "actor_label": "ben",
                    },
                ]
            },
        )

    _patch_dispatch(monkeypatch, router)
    verdict = guard.evaluate_dirty_main_for_item(
        "/repo",
        item_id=1,
        public_ref="YOK-1",
        session_id="caller",
        needed_paths=("foo.py",),
    )
    assert "yoke say --preview --session abc-123" in verdict.narrative
    assert "yoke say --session abc-123 --stdin" in verdict.narrative
    assert "(no current item)" in verdict.narrative


def test_untracked_scratch_warns_and_does_not_block(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_untracked("scratch.py")))

    def router(*, function_id, target, payload=None, **_k):
        return _resp(function_id, result={"rows": []})

    _patch_dispatch(monkeypatch, router)
    verdict = guard.evaluate_dirty_main_for_item(
        "/repo",
        item_id=1,
        public_ref="YOK-1",
        session_id="caller",
        needed_paths=("scratch.py",),
        source_root_prefixes=("src",),
    )
    assert verdict.blocked is False
    assert "scratch.py" in verdict.warning_note
    assert "not a worktree block" in verdict.warning_note


def test_declared_package_roots_do_not_block_docs_scratch(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_untracked("docs/notes.md")))
    blocked, kind, paths = guard.overlapping_dirty_main(
        "/repo", source_root_prefixes=["src"]
    )
    assert (blocked, kind, paths) == (False, "", ())


def test_untracked_under_declared_source_root_blocks(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_untracked("src/pkg/new.py")))
    blocked, kind, paths = guard.overlapping_dirty_main(
        "/repo", source_root_prefixes=["src"]
    )
    assert blocked is True
    assert kind == BLOCK_DIRTY_UNTRACKED
    assert paths == ("src/pkg/new.py",)


def test_lane_source_root_prefixes_read_architecture_roots(monkeypatch):
    def router(*, function_id, target, payload=None, **_k):
        if function_id == "items.detail.get":
            return _resp(
                function_id,
                result={"item": {"project": {"id": 1, "slug": "yoke"}}},
            )
        if function_id == "project_structure.get":
            return _resp(
                function_id,
                result={
                    "entries": [
                        {
                            "payload": {
                                "package_roots": {
                                    "pkg": [
                                        {"root": "src", "layout": "package_under_root"},
                                        {
                                            "root": "runtime/api",
                                            "layout": "package_is_root",
                                        },
                                    ]
                                }
                            }
                        }
                    ]
                },
            )
        raise AssertionError(function_id)

    _patch_dispatch(monkeypatch, router)
    assert guard.lane_source_root_prefixes(42) == ("src", "runtime/api")


def test_unknown_machine_falls_back_to_self_clear_recipe(monkeypatch):
    monkeypatch.setattr(guard, "_run", _fake_run(_git_tracked("foo.py")))

    def router(*, function_id, target, payload=None, **_k):
        return _resp(function_id, result={"rows": []})

    _patch_dispatch(monkeypatch, router)
    verdict = guard.evaluate_dirty_main_for_item(
        "/repo",
        item_id=1,
        public_ref="YOK-1",
        session_id="caller",
        needed_paths=("foo.py",),
    )
    assert "No live session on this machine" in verdict.narrative
    assert "yoke sessions list --liveness active" in verdict.narrative
