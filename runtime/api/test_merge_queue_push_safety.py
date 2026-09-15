"""Publishing a lane refuses while its candidate is still holding a landing."""

from pathlib import Path

import pytest

from yoke_core.domain import merge_queue_push_safety as safety
from yoke_core.engines import merge_worktree_pr_discovery as discovery
from yoke_core.domain.merge_queue_readiness import classify_readiness
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState, QueueMember

PR = "42"
BRANCH = "PRJ-9"
TARGET = "main"
QUEUED_HEAD = "a" * 40
NEW_HEAD = "c" * 40
CHECKOUT = Path("/tmp/checkout")


def _readiness(
    *,
    armed: bool = False,
    entry: bool = False,
    merged: bool = False,
    head: str = QUEUED_HEAD,
    queue_readable: bool = True,
):
    state = PrLandingState(
        merged=merged,
        closed=merged,
        auto_merge_active=armed,
        head_sha=head,
        merge_commit_sha="b" * 40 if merged else "",
    )
    members = [QueueMember(pr_num=PR, head_ref=BRANCH, state="AWAITING_CHECKS")]
    return classify_readiness(
        pr_number=PR,
        target=TARGET,
        state=state,
        members=(members if entry else []) if queue_readable else None,
        queue_error="" if queue_readable else "queue read failed",
    )


@pytest.fixture()
def wire(monkeypatch):
    """Stub the two GitHub reads the guard makes, at their own boundaries."""

    def _wire(
        readiness,
        *,
        declared=True,
        probe_error=None,
        rows=None,
        listing_error="",
    ):
        monkeypatch.setattr(
            "yoke_core.domain.merge_queue_route_selection."
            "project_declares_merge_queue",
            lambda _project: (declared, probe_error),
        )
        listing = discovery.BranchListing(
            rows=(_row(),) if rows is None else tuple(rows),
            error=listing_error,
        )
        seen: dict = {}

        def _listing(_ctx, *, query):
            seen["query"] = dict(query)
            return listing

        monkeypatch.setattr(safety, "list_branch_pull_requests", _listing)
        monkeypatch.setattr(
            safety,
            "read_merge_queue_readiness",
            lambda _ctx, *, pr_number, target: readiness,
        )
        return seen

    return _wire


def _row(number=PR, base=TARGET):
    return {"number": number, "base": {"ref": base}}


def _refusal(head_sha=NEW_HEAD):
    return safety.lane_publish_refusal(
        project="prj",
        checkout=CHECKOUT,
        branch=BRANCH,
        target=TARGET,
        head_sha=head_sha,
    )


def test_armed_candidate_refuses_a_correction_push(wire):
    wire(_readiness(armed=True))
    refusal = _refusal()
    assert "still holding a landing" in refusal
    assert safety.HOLD_COMMAND in refusal
    assert QUEUED_HEAD in refusal


def test_enqueued_candidate_refuses_a_correction_push(wire):
    wire(_readiness(entry=True))
    refusal = _refusal()
    assert "queue-entry=AWAITING_CHECKS" in refusal
    assert safety.HOLD_COMMAND in refusal


def test_republishing_the_head_the_queue_holds_is_allowed(wire):
    wire(_readiness(entry=True))
    assert _refusal(head_sha=QUEUED_HEAD) == ""


def test_merged_candidate_leaves_publishing_to_the_landing_paths(wire):
    wire(_readiness(merged=True))
    assert _refusal() == ""


def test_candidate_neither_armed_nor_queued_is_publishable(wire):
    wire(_readiness())
    assert _refusal() == ""


def test_unreadable_queue_refuses_rather_than_assuming_it_is_safe(wire):
    wire(_readiness(armed=True, queue_readable=False))
    refusal = _refusal()
    assert "could not be read" in refusal
    assert "queue read failed" in refusal
    assert safety.HOLD_COMMAND in refusal


def test_branch_with_no_open_pull_request_is_publishable(wire):
    """An empty listing is an answer; an unread listing is not."""
    wire(_readiness(entry=True), rows=())
    assert _refusal() == ""


def test_unreadable_listing_refuses_instead_of_reading_as_no_candidate(wire):
    """An auth or transport failure must not look like a branch with no landing."""
    wire(_readiness(), listing_error="pull request listing unavailable: no token")
    refusal = _refusal()
    assert "could not be read" in refusal
    assert "no token" in refusal
    assert safety.HOLD_COMMAND in refusal


def test_unreadable_capability_probe_refuses(wire):
    """Not knowing whether the project queues is not the same as not queuing."""
    wire(_readiness(), declared=False, probe_error="control plane unreachable")
    refusal = _refusal()
    assert "merge-queue capability" in refusal
    assert "control plane unreachable" in refusal


def test_the_listing_is_filtered_to_the_branch_and_the_target(wire):
    seen = wire(_readiness(entry=True))
    _refusal()
    assert seen["query"] == {"state": "open", "base": TARGET}


def test_a_pull_request_onto_another_base_never_answers_for_this_target(wire):
    """One head can hold open pull requests onto several bases."""
    wire(_readiness(entry=True), rows=(_row(number="99", base="release"),))
    assert _refusal() == ""


def test_a_listing_row_without_a_number_refuses_rather_than_guessing(wire):
    wire(_readiness(), rows=({"base": {"ref": TARGET}},))
    assert "could not be read" in _refusal()


def test_project_that_does_not_route_through_the_queue_is_unaffected(wire):
    wire(_readiness(entry=True), declared=False)
    assert _refusal() == ""


def test_publishing_a_held_lane_raises_its_own_error(wire):
    """The refusal carries its own recovery; a force-push is the wrong one."""
    wire(_readiness(entry=True))
    with pytest.raises(safety.LanePublishBlocked, match="still holding a landing"):
        safety.require_publishable_lane(
            project="prj",
            checkout=CHECKOUT,
            branch=BRANCH,
            target=TARGET,
            head_sha=NEW_HEAD,
        )


def test_the_landing_publish_reports_the_block_with_its_own_recovery(monkeypatch):
    """A force-push recovery would put the correction under the live landing."""
    from runtime.api.merge_queue_landing_test_helpers import CHECKOUT as ROOT, ctx
    from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
    from yoke_core.domain import qa_case_ci_lane

    monkeypatch.setattr(landing_pr_mod.git, "remote_head_of", lambda *_a: "f" * 40)

    def blocked_push(*_a, **_kw):
        raise safety.LanePublishBlocked("pull request 42 is still holding a landing")

    monkeypatch.setattr(qa_case_ci_lane, "push_lane", blocked_push)
    error = landing_pr_mod._publish_lane_head(
        ctx(repo_root=ROOT), lane_head=NEW_HEAD
    )
    assert error == "pull request 42 is still holding a landing"
    assert "--force-with-lease" not in error


def _push_lane_guarded(monkeypatch):
    """Drive the real publish path down to its guard; origin must stay untouched."""
    from yoke_core.domain import qa_case_ci_lane

    monkeypatch.setattr(
        qa_case_ci_lane, "ref_sha", lambda _checkout, _ref: NEW_HEAD
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "_git",
        lambda *_a, **_kw: pytest.fail("origin was touched before the guard"),
    )
    qa_case_ci_lane.push_lane(CHECKOUT, BRANCH, project="prj", target=TARGET)


def test_the_publish_path_refuses_a_live_candidate_before_touching_origin(
    wire, monkeypatch
):
    """Every lane reaches origin through push_lane, so the guard lives there."""
    wire(_readiness(entry=True))
    with pytest.raises(safety.LanePublishBlocked, match="still holding a landing"):
        _push_lane_guarded(monkeypatch)


def test_the_publish_path_refuses_when_the_listing_could_not_be_read(
    wire, monkeypatch
):
    """An outage must not reach origin as though the branch had no landing."""
    wire(_readiness(), listing_error="pull request listing failed: 503")
    with pytest.raises(safety.LanePublishBlocked, match="could not be read"):
        _push_lane_guarded(monkeypatch)


def test_the_publish_path_proceeds_when_nothing_is_holding_the_branch(
    wire, monkeypatch
):
    """A clean listing is an answer, so the publish is allowed to happen."""
    from yoke_core.domain import qa_case_ci_lane

    wire(_readiness(), rows=())
    calls: list = []
    monkeypatch.setattr(
        qa_case_ci_lane, "ref_sha", lambda _checkout, _ref: NEW_HEAD
    )
    monkeypatch.setattr(
        qa_case_ci_lane, "_git", lambda *a, **_kw: calls.append(a[1])
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "_git_output",
        lambda *a, **_kw: calls.append(a[1]) or "",
    )
    qa_case_ci_lane.push_lane(CHECKOUT, BRANCH, project="prj", target=TARGET)
    assert calls == ["fetch", "push"]
