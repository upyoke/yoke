"""The integration dependency gate holds both landing routes."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_queue_route_selection as selection_mod
from yoke_core.domain.integration_dependency_refusal import (
    DEPENDENCY_GATE_FUNCTION_ID,
    integration_dependency_refusal,
)
from yoke_core.domain.merge_queue_route import QueueLandingOutcome
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

_BLOCKER = {
    "blocking_item": "YOK-100",
    "blocking_status": "implementing",
    "gate_point": "integration",
    "satisfaction": "merged",
    "rationale": "needs the new column",
}


def _gate(result=None, *, error=None, raises=None):
    seen: list = []

    def dispatch(*, function_id, target, payload, **_kw):
        seen.append((function_id, target, payload))
        if raises is not None:
            raise raises
        if error is not None:
            return SimpleNamespace(
                success=False, result=None, error=SimpleNamespace(message=error)
            )
        return SimpleNamespace(success=True, result=result, error=None)

    dispatch.seen = seen
    return dispatch


def _refusal(dispatch, **kwargs):
    return integration_dependency_refusal(
        item_id=7, public_ref="YOK-200", dispatch=dispatch, **kwargs
    )


def test_clear_gate_admits_the_landing():
    dispatch = _gate({"is_blocked": False, "unsatisfied_blockers": []})
    assert _refusal(dispatch) == ""
    function_id, target, payload = dispatch.seen[0]
    assert function_id == DEPENDENCY_GATE_FUNCTION_ID
    assert target.public_ref == "YOK-200"
    assert payload == {"gate_point": "integration"}


def test_blocked_gate_names_each_blocker_and_the_recovery():
    refusal = _refusal(
        _gate({"is_blocked": True, "unsatisfied_blockers": [_BLOCKER]}),
        resume_command="yoke merge item YOK-200 --json",
    )
    assert (
        "Keep your work claim and lane; do not release or end the session; the notice wakes you as holder."
        in refusal
    )
    assert (
        'yoke sessions touch --mode parked --reason "awaiting <BLOCKER> integration"'
        in refusal
    )
    assert refusal.startswith("integration_dependency_blocked: YOK-200")
    assert "YOK-100 (implementing): needs the new column" in refusal
    assert "re-run `yoke merge item YOK-200 --json`" in refusal


@pytest.mark.parametrize(
    "dispatch",
    [_gate(error="relay unavailable"), _gate(raises=RuntimeError("relay unavailable"))],
)
def test_unreadable_gate_fails_closed(dispatch):
    refusal = _refusal(dispatch)
    assert refusal.startswith("integration_dependency_gate_unavailable: ")
    assert "relay unavailable" in refusal
    assert "re-run `yoke merge item YOK-200`" in refusal


def _route(monkeypatch, *, declared, gate):
    """Route one item whose predecessor state ``gate`` answers."""
    landed: dict = {}
    monkeypatch.setattr(
        selection_mod,
        "project_declares_merge_queue",
        lambda project, dispatch=None: (declared, None),
    )
    monkeypatch.setattr(selection_mod, "candidate_review_refusal", lambda **_kw: "")
    monkeypatch.setattr(
        selection_mod, "_find_worktree", lambda branch, repo_root: "/tmp/lane"
    )

    def enqueue(ctx, **kwargs):
        landed["route"] = "queue"
        return QueueLandingOutcome(
            ok=True, exit_code=0, pr_num="42", commit_sha=kwargs["commit_sha"]
        )

    def merge_locally(**_kwargs):
        landed["route"] = "standalone"
        return StandaloneMergeOutcome(ok=True, exit_code=0, already_merged=False)

    monkeypatch.setattr(selection_mod, "land_item_through_merge_queue", enqueue)
    monkeypatch.setattr(selection_mod, "merge_standalone_branch", merge_locally)
    outcome = selection_mod.route_standalone_landing(
        item_id=7,
        branch="YOK-200",
        target="main",
        commit_sha="c" * 40,
        repo_root="/tmp/repo",
        project="yoke",
        public_ref="YOK-200",
        dispatch=gate,
    )
    return outcome, landed.get("route")


@pytest.mark.parametrize("declared", [True, False])
def test_unmerged_predecessor_refuses_before_either_route(monkeypatch, declared):
    blocked = _gate({"is_blocked": True, "unsatisfied_blockers": [_BLOCKER]})
    outcome, route = _route(monkeypatch, declared=declared, gate=blocked)
    assert not outcome.ok
    assert route is None
    assert "integration_dependency_blocked" in outcome.error
    assert "YOK-100" in outcome.error


@pytest.mark.parametrize(
    ("declared", "expected_route"), [(True, "queue"), (False, "standalone")]
)
def test_item_lands_once_its_predecessor_merges(monkeypatch, declared, expected_route):
    clear = _gate({"is_blocked": False, "unsatisfied_blockers": []})
    outcome, route = _route(monkeypatch, declared=declared, gate=clear)
    assert outcome.ok
    assert route == expected_route
