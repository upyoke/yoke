"""The merge_group run read: exact workflow, exact train, named absence."""

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


def _wire_runs(monkeypatch, runs):
    monkeypatch.setattr(
        train_run_mod,
        "resolve_auth_detail",
        lambda ctx, perms: (_auth(), None),
    )
    monkeypatch.setattr(
        train_run_mod,
        "request_with_retry",
        lambda req, *, token, **_kw: _response({"workflow_runs": runs}),
    )
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
    assert "no merge_group workflow run identified" in note
    assert "https://runs/7" not in note


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
    assert "no merge_group workflow run identified" in note
    assert "combined head" in note


def test_read_train_run_without_any_run_is_named(monkeypatch):
    _wire_runs(monkeypatch, [])
    run, note = train_run_mod.read_train_run(_ctx(), "42")
    assert run is None
    assert "no merge_group workflow run" in note
