"""Post-rebase QA materialization tolerates workflows without the transition.

``materialize_for_item`` validates the transition against the item's pinned
workflow *before* it reads any attachments, so a workflow that never declares
the post-rebase transition fails materialization even though it has no
pre-merge-verification plan to snapshot. That is "no post-rebase QA case", not
a verification failure — every Dash merge would otherwise die here.

A workflow that *does* declare the transition keeps failing loudly: that is a
real materialization failure and must still block the merge.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.engines import merge_worktree_tests as mod


ITEM_ID = 4242


def _resp(success: bool, *, result=None, code: str = "", message: str = ""):
    error = None if success else SimpleNamespace(code=code, message=message)
    return SimpleNamespace(success=success, result=result, error=error)


def _materialization_failed():
    return _resp(
        False,
        code="post_rebase_requirement_failed",
        message="workflow transition 'release' is not in dash@3",
    )


def _version_definition(transitions):
    return _resp(True, result={"definition": {"transitions": transitions}})


DASH_TRANSITIONS = [
    {"from_stage_id": "idea", "to_stage_id": "implementing"},
    {"from_stage_id": "implementing", "to_stage_id": "reviewing-implementation"},
    {"from_stage_id": "reviewing-implementation", "to_stage_id": "done"},
]

RELEASING_TRANSITIONS = [
    {"from_stage_id": "implemented", "to_stage_id": "release"},
    {"from_stage_id": "release", "to_stage_id": "done"},
]


def _patch_dispatcher(monkeypatch, responses):
    """Serve queued responses keyed by function id; record the call order."""
    calls: list[str] = []

    def fake(*, function_id, target, payload):
        calls.append(function_id)
        return responses[function_id]

    monkeypatch.setattr(mod, "call_dispatcher", fake)
    return calls


@pytest.fixture
def ctx():
    return SimpleNamespace(item_id=ITEM_ID)


class TestPostRebaseTransitionAbsent:
    def test_workflow_without_the_transition_skips_the_case(
        self, ctx, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = _patch_dispatcher(monkeypatch, {
            "merge.tests.post_rebase_requirement": _materialization_failed(),
            "workflows.item.get": _resp(
                True, result={"workflow_id": "dash", "workflow_version": 3},
            ),
            "workflows.version.get": _version_definition(DASH_TRANSITIONS),
        })

        assert mod._post_rebase_requirement_id(ctx) is None
        assert "workflows.version.get" in calls

    def test_workflow_with_the_transition_still_raises(
        self, ctx, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A real materialization failure must keep blocking the merge."""
        _patch_dispatcher(monkeypatch, {
            "merge.tests.post_rebase_requirement": _materialization_failed(),
            "workflows.item.get": _resp(
                True, result={"workflow_id": "issue", "workflow_version": 5},
            ),
            "workflows.version.get": _version_definition(RELEASING_TRANSITIONS),
        })

        with pytest.raises(RuntimeError, match="post-rebase QA materialization"):
            mod._post_rebase_requirement_id(ctx)

    def test_unresolvable_workflow_identity_raises(
        self, ctx, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Never explain a failure away on a read we could not complete."""
        _patch_dispatcher(monkeypatch, {
            "merge.tests.post_rebase_requirement": _materialization_failed(),
            "workflows.item.get": _resp(False, code="relay_unavailable"),
        })

        with pytest.raises(RuntimeError, match="post-rebase QA materialization"):
            mod._post_rebase_requirement_id(ctx)


class TestPostRebaseUnchangedPaths:
    def test_success_returns_the_requirement_id(
        self, ctx, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = _patch_dispatcher(monkeypatch, {
            "merge.tests.post_rebase_requirement": _resp(
                True, result={"requirement_id": 77},
            ),
        })

        assert mod._post_rebase_requirement_id(ctx) == 77
        assert calls == ["merge.tests.post_rebase_requirement"], (
            "the happy path must not pay for the workflow lookup"
        )

    def test_relay_unavailability_still_skips(
        self, ctx, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_dispatcher(monkeypatch, {
            "merge.tests.post_rebase_requirement": _resp(
                False, code="relay_unavailable",
            ),
        })

        assert mod._post_rebase_requirement_id(ctx) is None
