"""No landing shape gets past an uncleared candidate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_candidate_review_admission as admission_mod
from yoke_core.domain import merge_queue_route_selection as selection_mod
from yoke_core.domain.merge_queue_route import QueueLandingOutcome
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome


HEAD = "c" * 40


def _response(result):
    return SimpleNamespace(success=True, result=result, error=None)


def _verdict(**overrides):
    base = {
        "required": True,
        "satisfied": False,
        "item_id": 1,
        "commit_sha": HEAD,
        "reason": "a reviewer has not yet cleared this candidate",
        "request_id": 77,
        "request_status": "pending",
        "resolution_action": None,
        "superseded_request_ids": [],
    }
    base.update(overrides)
    return base


def _dispatch_for(verdict, seen=None):
    def dispatch(*, function_id, target, payload, **_kw):
        if function_id == admission_mod.EVALUATE_FUNCTION_ID:
            if seen is not None:
                seen.update(payload=payload, target=target)
            return _response(verdict)
        # Everything else in this boundary is the capability probe.
        return _response({"rows": [[0]]})

    return dispatch


@pytest.fixture(autouse=True)
def quiet_git(monkeypatch):
    """The repository is not the subject here; the clearance is."""
    monkeypatch.setattr(selection_mod.git, "head_of", lambda *_a: HEAD)
    monkeypatch.setattr(
        admission_mod.git, "changed_files", lambda *_a: ("packages/a.py",)
    )


def _forbid(monkeypatch, message):
    def forbidden(*_args, **_kwargs):
        raise AssertionError(message)

    monkeypatch.setattr(selection_mod, "merge_standalone_branch", forbidden)
    monkeypatch.setattr(selection_mod, "land_item_through_merge_queue", forbidden)


def _route(dispatch, *, project="yoke"):
    return selection_mod.route_standalone_landing(
        item_id=1,
        branch="YOK-200",
        target="main",
        repo_root="/tmp/repo",
        project=project,
        public_ref="YOK-200",
        dispatch=dispatch,
    )


def test_the_queue_route_never_arms_an_uncleared_candidate(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (True, None),
    )
    _forbid(monkeypatch, "an uncleared candidate must not reach the queue")
    outcome = _route(_dispatch_for(_verdict()))
    assert not outcome.ok
    assert outcome.commit_sha == HEAD
    assert "merge_candidate_review" in outcome.error
    assert "Decision request 77" in outcome.error
    assert "yoke decision-requests resolve 77 approve" in outcome.error
    assert "Nothing has been merged" in outcome.error


def test_the_direct_merge_route_never_lands_an_uncleared_candidate(monkeypatch):
    """A project with no merge queue is held by the same review."""
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    _forbid(monkeypatch, "an uncleared candidate must not merge locally")
    outcome = _route(_dispatch_for(_verdict()), project="platform")
    assert not outcome.ok
    assert "Decision request 77" in outcome.error


def test_a_cleared_candidate_lands(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    landed = {}

    def fake_standalone(**kwargs):
        landed.update(kwargs)
        return StandaloneMergeOutcome(ok=True, exit_code=0, already_merged=False)

    monkeypatch.setattr(selection_mod, "merge_standalone_branch", fake_standalone)
    outcome = _route(_dispatch_for(_verdict(satisfied=True)))
    assert outcome.ok
    assert landed["branch"] == "YOK-200"


def test_an_item_that_needs_no_review_is_unaffected(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (True, None),
    )
    monkeypatch.setattr(
        selection_mod,
        "land_item_through_merge_queue",
        lambda _ctx, **kwargs: QueueLandingOutcome(
            ok=True, exit_code=0, pr_num="42", commit_sha=kwargs["commit_sha"],
        ),
    )
    outcome = _route(
        _dispatch_for(_verdict(required=False, satisfied=True, request_id=None))
    )
    assert outcome.ok
    assert outcome.pr_num == "42"


def test_the_review_is_asked_about_the_exact_head_and_its_files(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    monkeypatch.setattr(
        selection_mod,
        "merge_standalone_branch",
        lambda **_kw: StandaloneMergeOutcome(
            ok=True, exit_code=0, already_merged=False
        ),
    )
    seen: dict = {}
    _route(_dispatch_for(_verdict(satisfied=True), seen))
    assert seen["payload"]["commit_sha"] == HEAD
    assert seen["payload"]["branch"] == "YOK-200"
    assert seen["payload"]["target"] == "main"
    assert seen["payload"]["touched_files"] == ["packages/a.py"]
    assert seen["target"].item_id == 1


def test_a_rejected_candidate_is_refused_with_its_verdict(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    _forbid(monkeypatch, "a rejected candidate must not land")
    outcome = _route(
        _dispatch_for(
            _verdict(request_status="resolved", resolution_action="reject")
        )
    )
    assert not outcome.ok
    assert "reviewed and rejected" in outcome.error
    assert "the new commit raises its own review" in outcome.error


def test_a_control_plane_without_the_function_lands_normally(monkeypatch):
    """The slice has to survive its own rollout.

    A universe learns the posture key and this function in one deploy, so a
    server that does not serve it has no item that can require a review.
    Refusing there would block every merge on every project until the
    deploy landed -- including the merge that ships it.
    """
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    landed = {}

    def fake_standalone(**kwargs):
        landed.update(kwargs)
        return StandaloneMergeOutcome(ok=True, exit_code=0, already_merged=False)

    monkeypatch.setattr(selection_mod, "merge_standalone_branch", fake_standalone)

    def dispatch(*, function_id, **_kw):
        if function_id == admission_mod.EVALUATE_FUNCTION_ID:
            return SimpleNamespace(
                success=False,
                result=None,
                error=SimpleNamespace(
                    code="function_version_skew",
                    message="the active HTTPS env does not serve function",
                ),
            )
        return _response({"rows": [[0]]})

    outcome = _route(dispatch)
    assert outcome.ok
    assert landed["branch"] == "YOK-200"


def test_an_unreadable_answer_refuses_rather_than_landing(monkeypatch):
    """A boundary that cannot ask must not answer with a landing."""
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    _forbid(monkeypatch, "an unreadable review must not land")

    def dispatch(*, function_id, **_kw):
        if function_id == admission_mod.EVALUATE_FUNCTION_ID:
            return SimpleNamespace(
                success=False,
                result=None,
                error=SimpleNamespace(code="relay_error", message="relay unavailable"),
            )
        return _response({"rows": [[0]]})

    outcome = _route(dispatch)
    assert not outcome.ok
    assert "could not be checked" in outcome.error
    assert "relay unavailable" in outcome.error
