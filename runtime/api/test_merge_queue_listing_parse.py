"""The pull-request listing as GitHub actually returns it.

Sibling of ``test_merge_queue_push_safety``, which stubs the listing to
cover the guard's decisions. These drive the real REST read and the real
parse — only the transport is replaced — so a response shape the parser
mishandles cannot be stubbed away.
"""

from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import merge_queue_push_safety as safety
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.domain.merge_queue_readiness import classify_readiness
from yoke_core.engines import merge_worktree_pr_discovery as discovery
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState, QueueMember

PR = "42"
BRANCH = "PRJ-9"
TARGET = "main"
QUEUED_HEAD = "a" * 40
NEW_HEAD = "c" * 40
CHECKOUT = Path("/tmp/checkout")


def _readiness():
    """A candidate holding a queue entry at a head that is not NEW_HEAD."""
    return classify_readiness(
        pr_number=PR,
        target=TARGET,
        state=PrLandingState(
            merged=False, closed=False, auto_merge_active=False,
            head_sha=QUEUED_HEAD,
        ),
        members=[QueueMember(pr_num=PR, head_ref=BRANCH, state="AWAITING_CHECKS")],
    )


def _refusal():
    return safety.lane_publish_refusal(
        project="prj",
        checkout=CHECKOUT,
        branch=BRANCH,
        target=TARGET,
        head_sha=NEW_HEAD,
    )


def _wire_real_listing(monkeypatch, body):
    """Serve ``body`` from the REST boundary; parse and guard for real."""
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_route_selection."
        "project_declares_merge_queue",
        lambda _project: (True, None),
    )
    monkeypatch.setattr(
        discovery,
        "resolve_auth",
        lambda *_a, **_kw: SimpleNamespace(token="tok", repo="acme/widgets"),
    )
    monkeypatch.setattr(
        discovery,
        "request_with_retry",
        lambda _req, *, token, **_kw: RestResponse(
            status=200, headers={}, body=body
        ),
    )
    monkeypatch.setattr(
        safety,
        "read_merge_queue_readiness",
        lambda _ctx, *, pr_number, target: _readiness(),
    )


def test_a_null_entry_in_the_listing_is_not_an_empty_listing(monkeypatch):
    """Dropping it would turn a malformed response into 'no candidate'."""
    _wire_real_listing(monkeypatch, [None])
    refusal = _refusal()
    assert "could not be read" in refusal
    assert "not a pull request object" in refusal


def test_a_row_without_a_base_is_not_a_row_onto_another_branch(monkeypatch):
    """[{}] must not read as a pull request that targets somewhere else."""
    _wire_real_listing(monkeypatch, [{"number": PR}])
    refusal = _refusal()
    assert "could not be read" in refusal
    assert "no readable base branch" in refusal


def test_a_base_that_is_not_an_object_refuses(monkeypatch):
    _wire_real_listing(monkeypatch, [{"number": PR, "base": "main"}])
    assert "no readable base branch" in _refusal()


def test_a_base_object_without_a_ref_refuses(monkeypatch):
    _wire_real_listing(monkeypatch, [{"number": PR, "base": {}}])
    assert "no readable base branch" in _refusal()


def test_a_real_listing_onto_another_base_still_permits_the_push(monkeypatch):
    """A base that is readable and explicitly different is an answer."""
    _wire_real_listing(
        monkeypatch, [{"number": "99", "base": {"ref": "release"}}]
    )
    assert _refusal() == ""


def test_a_real_listing_onto_this_base_refuses_a_live_candidate(monkeypatch):
    _wire_real_listing(monkeypatch, [{"number": PR, "base": {"ref": TARGET}}])
    assert "still holding a landing" in _refusal()


def test_a_real_empty_listing_permits_the_push(monkeypatch):
    _wire_real_listing(monkeypatch, [])
    assert _refusal() == ""


def test_a_response_that_is_not_an_array_refuses(monkeypatch):
    _wire_real_listing(monkeypatch, {"message": "Not Found"})
    assert "no array of pull requests" in _refusal()
