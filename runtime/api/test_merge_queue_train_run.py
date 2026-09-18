"""The merge_group run read: exact workflow, exact train, named absence.

The reach matters as much as the match. A member that parks across a release
wait asks these questions hours and dozens of trains after its own run, so
the tests below pin the two properties that keep it answerable at that
distance — the request is scoped to the declared workflow, and a known
combined head is asked for by ``head_sha`` rather than searched for.
"""

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import merge_worktree_pr_train_run as train_run_mod
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-100"), project="yoke")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _response(body) -> RestResponse:
    return RestResponse(status=200, headers={}, body=body)


def _wire_runs(monkeypatch, runs, *, requests=None):
    """Answer every page with ``runs``; optionally record the requests."""
    monkeypatch.setattr(
        train_run_mod,
        "resolve_auth_detail",
        lambda ctx, perms: (_auth(), None),
    )

    def _request(req, *, token, **_kw):
        if requests is not None:
            requests.append(req)
        return _response({"workflow_runs": runs})

    monkeypatch.setattr(train_run_mod, "request_with_retry", _request)
    monkeypatch.setattr(
        train_run_mod,
        "project_ci_workflow_file",
        lambda _project: "yoke-ci.yml",
    )


def test_read_train_run_matches_required_workflow_and_queue_ref_marker(monkeypatch):
    _wire_runs(
        monkeypatch,
        [
            {
                "path": ".github/workflows/cla.yml",
                "head_branch": "gh-readonly-queue/main/pr-42-def",
                "conclusion": "success",
                "status": "completed",
                "head_sha": "a" * 40,
                "html_url": "https://runs/7",
            },
            {
                "path": ".github/workflows/yoke-ci.yml",
                "head_branch": "gh-readonly-queue/main/pr-42-def",
                "conclusion": "failure",
                "status": "completed",
                "head_sha": "b" * 40,
                "html_url": "https://runs/42",
            },
        ],
    )
    run, note = train_run_mod.read_train_run(_ctx(), "42")
    assert note is None
    assert run.conclusion == "failure"
    assert run.head_sha == "b" * 40
    assert run.url == "https://runs/42"


def test_read_train_run_asks_the_declared_workflows_own_runs_collection(monkeypatch):
    """A second merge_group workflow must not spend this reader's budget."""
    requests: list = []
    _wire_runs(monkeypatch, [], requests=requests)
    train_run_mod.read_train_run(_ctx(), "42")
    assert requests
    for request in requests:
        assert request.path == (
            "/repos/upyoke/yoke/actions/workflows/yoke-ci.yml/runs"
        )
        assert request.query["event"] == "merge_group"


def test_read_train_run_anchors_a_known_combined_head_by_head_sha(monkeypatch):
    """An indexed lookup reaches a train of any age, so it is asked first."""
    combined = "c" * 40
    requests: list = []
    _wire_runs(
        monkeypatch,
        [
            {
                "path": ".github/workflows/yoke-ci.yml",
                "head_branch": "gh-readonly-queue/main/pr-7-abc",
                "conclusion": "success",
                "status": "completed",
                "head_sha": combined,
                "html_url": "https://runs/7",
            },
        ],
        requests=requests,
    )
    run, note = train_run_mod.read_train_run(
        _ctx(), "42", covering_sha=combined,
    )
    assert note is None
    assert run.head_sha == combined
    # The anchored request is the first one, and it carries the head.
    assert requests[0].query["head_sha"] == combined


def test_read_train_run_never_substitutes_another_trains_run(monkeypatch):
    """Another train's green is not this pull request's, at any recency."""
    _wire_runs(
        monkeypatch,
        [
            {
                "path": ".github/workflows/yoke-ci.yml",
                "head_branch": "gh-readonly-queue/main/pr-7-abc",
                "conclusion": "success",
                "status": "completed",
                "head_sha": "a" * 40,
                "html_url": "https://runs/7",
            },
        ],
    )
    run, note = train_run_mod.read_train_run(_ctx(), "42")
    assert run is None
    assert "no merge_group workflow run identified" in note.reason
    assert "https://runs/7" not in note.reason


def test_read_train_run_matches_sibling_by_combined_head_sha(monkeypatch):
    """GitHub names a batch train after one member; siblings share its head."""
    combined = "c" * 40
    _wire_runs(
        monkeypatch,
        [
            {
                "path": ".github/workflows/yoke-ci.yml",
                "head_branch": "gh-readonly-queue/main/pr-7-abc",
                "conclusion": "success",
                "status": "completed",
                "head_sha": combined,
                "html_url": "https://runs/7",
            },
        ],
    )
    run, note = train_run_mod.read_train_run(
        _ctx(), "42", covering_sha=combined,
    )
    assert note is None
    assert run.head_sha == combined
    assert run.url == "https://runs/7"


def test_read_train_run_covering_sha_does_not_adopt_a_different_head(monkeypatch):
    _wire_runs(
        monkeypatch,
        [
            {
                "path": ".github/workflows/yoke-ci.yml",
                "head_branch": "gh-readonly-queue/main/pr-7-abc",
                "conclusion": "success",
                "status": "completed",
                "head_sha": "a" * 40,
                "html_url": "https://runs/7",
            },
        ],
    )
    run, note = train_run_mod.read_train_run(
        _ctx(), "42", covering_sha="b" * 40,
    )
    assert run is None
    assert "no merge_group workflow run identified" in note.reason
    assert "b" * 40 in note.reason


def test_read_train_run_without_any_run_is_named(monkeypatch):
    _wire_runs(monkeypatch, [])
    run, note = train_run_mod.read_train_run(_ctx(), "42")
    assert run is None
    assert "no merge_group workflow run" in note.reason


def test_completed_search_that_found_nothing_does_not_prescribe_a_retry(monkeypatch):
    """The anchored answer is stable, so "run it again" is not a recovery."""
    _wire_runs(monkeypatch, [])
    _run, note = train_run_mod.read_train_run(_ctx(), "42")
    assert note.retryable is False
    assert note.recovery
    assert "operator decision" in note.recovery


def test_a_provider_read_that_failed_is_retryable(monkeypatch):
    """A refused read answered nothing, so asking again may still work."""
    from yoke_core.domain.gh_rest_transport import RestTransportError

    monkeypatch.setattr(
        train_run_mod,
        "resolve_auth_detail",
        lambda ctx, perms: (_auth(), None),
    )
    monkeypatch.setattr(
        train_run_mod,
        "project_ci_workflow_file",
        lambda _project: "yoke-ci.yml",
    )

    def _boom(req, *, token, **_kw):
        raise RestTransportError("502 upstream")

    monkeypatch.setattr(train_run_mod, "request_with_retry", _boom)
    run, note = train_run_mod.read_train_run(_ctx(), "42")
    assert run is None
    assert note.retryable is True
    assert "502 upstream" in note.reason
