"""The branch a queue landing opens its pull request for.

Two ways that branch goes wrong. It can be named something git accepts and a
reader of the name does not — anything carrying a slash. And it can be
missing from origin entirely, because publishing the lane is the verification
gate's step, so a landing whose verification was satisfied any other way
reaches GitHub with a branch GitHub has never seen and is refused as a bare
HTTP 422.
"""

import pytest

from runtime.api.merge_queue_landing_test_helpers import (
    CHECKOUT,
    LANE_SHA,
    MERGED,
    ctx,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import qa_case_ci_lane
from yoke_core.domain.merge_queue_declaration_apply import _branch_from_ruleset
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.engines.merge_worktree_pr_rest import PrCreateResult


# --- A branch name git accepts, the landing accepts -------------------------


def test_a_lane_branch_containing_a_slash_lands(monkeypatch):
    """git accepts 'feature/x' as a branch name, so the landing must too."""
    branch = "feature/queue-landing"
    wire_happy_path(monkeypatch, landing_states=[MERGED])
    seen: dict = {}
    monkeypatch.setattr(
        close_out_mod, "read_pr_changed_files",
        lambda merge_ctx, _pr: seen.update(branch=merge_ctx.args.branch)
        or (("a.py",), None),
    )
    outcome = land(ctx=ctx(branch), item_ref=branch)
    assert outcome.ok
    assert seen["branch"] == branch


@pytest.mark.parametrize(
    "include, expected",
    [
        ("refs/heads/main", "main"),
        ("refs/heads/release/v2", "release/v2"),
        ("~DEFAULT_BRANCH", "~DEFAULT_BRANCH"),
    ],
)
def test_the_ruleset_branch_is_read_past_the_ref_prefix(include, expected):
    """The last path segment names a branch the repository does not have."""
    ruleset = {"conditions": {"ref_name": {"include": [include]}}}
    assert _branch_from_ruleset(ruleset) == expected


# --- The landing publishes its own precondition -----------------------------


def _wire_pull_request_create(monkeypatch, *, on_origin, created) -> list:
    """Wire a landing with no existing pull request; return the call order."""
    order: list[str] = []
    monkeypatch.setattr(
        landing_pr_mod, "find_landable_pull_request",
        lambda _ctx, lane_head="": (None, None, ""),
    )
    monkeypatch.setattr(
        landing_pr_mod.git, "remote_branch_exists", lambda *_a: on_origin
    )

    def create(_ctx, *, title, body):
        order.append("create")
        return created

    monkeypatch.setattr(landing_pr_mod, "create_pr", create)
    return order


def _ensure():
    return landing_pr_mod.ensure_landing_pull_request(
        ctx(repo_root=CHECKOUT), "YOK-200", lane_head=LANE_SHA,
    )


def test_landing_publishes_a_branch_origin_has_never_seen(monkeypatch):
    """A waived gate never ran, and it is the gate that publishes the lane."""
    order = _wire_pull_request_create(
        monkeypatch,
        on_origin=False,
        created=PrCreateResult(pr_url="url", pr_num="42"),
    )
    pushed: dict = {}

    def push(checkout, branch, *, source_ref="HEAD"):
        order.append("push")
        pushed.update(
            checkout=str(checkout), branch=branch, source_ref=source_ref
        )

    monkeypatch.setattr(qa_case_ci_lane, "push_lane", push)
    assert _ensure() == ("42", None)
    assert order == ["push", "create"]
    assert pushed == {
        "checkout": CHECKOUT, "branch": "YOK-200", "source_ref": LANE_SHA,
    }


def test_landing_does_not_republish_a_branch_origin_already_has(monkeypatch):
    """The gate's push is the normal case; this one stays a no-op."""
    _wire_pull_request_create(
        monkeypatch,
        on_origin=True,
        created=PrCreateResult(pr_url="url", pr_num="42"),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("a published branch must not be pushed again")

    monkeypatch.setattr(qa_case_ci_lane, "push_lane", forbidden)
    assert _ensure() == ("42", None)


def test_a_branch_that_cannot_be_published_is_named_before_the_pull_request(
    monkeypatch,
):
    """A failed push is the landing's own precondition, not GitHub's refusal."""
    _wire_pull_request_create(
        monkeypatch,
        on_origin=False,
        created=PrCreateResult(pr_url="", pr_num="", error_detail="unreached"),
    )

    def failing_push(*_a, **_kw):
        raise QaCaseExecutionError(
            "pushing lane branch 'YOK-200' to origin failed: permission denied"
        )

    monkeypatch.setattr(qa_case_ci_lane, "push_lane", failing_push)
    monkeypatch.setattr(
        landing_pr_mod, "create_pr",
        lambda *_a, **_kw: pytest.fail("no pull request for an absent branch"),
    )
    pr_num, error = _ensure()
    assert pr_num == ""
    assert "absent from origin" in error
    assert "permission denied" in error


def test_a_refused_pull_request_names_the_missing_branch_and_the_push(
    monkeypatch,
):
    """GitHub reports a branch it does not have as an unexplained 422."""
    _wire_pull_request_create(
        monkeypatch,
        on_origin=False,
        created=PrCreateResult(
            pr_url="", pr_num="",
            error_detail="pr create rejected (HTTP 422): Unprocessable Entity",
        ),
    )
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", lambda *_a, **_kw: None)
    pr_num, error = _ensure()
    assert pr_num == ""
    assert "HTTP 422" in error
    assert "not on origin" in error
    assert "push --force-with-lease origin refs/heads/YOK-200" in error
