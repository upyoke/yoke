"""Batch receipt observation and covering-evidence recording."""

from types import SimpleNamespace

from yoke_core.domain import merge_queue_batch_receipt as receipt_mod
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.engines import merge_worktree_pr_queue as queue_mod
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-300"), project="yoke")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _response(body) -> RestResponse:
    return RestResponse(status=200, headers={}, body=body)


def _wire_transport(monkeypatch, *, runs):
    """Serve the PR read here and the merge_group run read where it lives."""
    for module in (receipt_mod, queue_mod):
        monkeypatch.setattr(
            module, "resolve_auth_detail", lambda ctx, perms: (_auth(), None),
        )

    def fake_request(req, *, token, **_kw):
        if "/pulls/" in req.path:
            return _response({"merge_commit_sha": "m" * 40})
        assert req.path.endswith("/actions/runs")
        assert req.query["event"] == "merge_group"
        return _response({"workflow_runs": runs})

    monkeypatch.setattr(receipt_mod, "request_with_retry", fake_request)
    monkeypatch.setattr(queue_mod, "request_with_retry", fake_request)
    monkeypatch.setattr(
        queue_mod, "project_ci_workflow_file", lambda _project: "yoke-ci.yml",
    )


def test_observe_batch_matches_queue_ref_marker_and_required_workflow(monkeypatch):
    _wire_transport(monkeypatch, runs=[
        {"path": ".github/workflows/cla.yml",
         "head_branch": "gh-readonly-queue/main/pr-42-def",
         "head_sha": "a" * 40, "html_url": "https://runs/7",
         "conclusion": "success"},
        {"path": ".github/workflows/yoke-ci.yml",
         "head_branch": "gh-readonly-queue/main/pr-42-def",
         "head_sha": "b" * 40, "html_url": "https://runs/42",
         "conclusion": "success"},
    ])
    receipt, warn = receipt_mod.observe_batch(
        _ctx(), pr_num="42", member_snapshot=("YOK-300", "YOK-301"),
    )
    assert warn is None
    assert receipt.head_sha == "b" * 40
    assert receipt.run_url == "https://runs/42"
    assert receipt.merge_sha == "m" * 40
    assert receipt.members == ("YOK-300", "YOK-301")


def test_observe_batch_never_adopts_another_trains_combined_head(monkeypatch):
    """Only the run carrying this pull request's marker names its head.

    The receipt is what covering-evidence readers compare trees by, so a
    head borrowed from a different train is worse than none: it asserts this
    member was validated by a run that never contained it.
    """
    _wire_transport(monkeypatch, runs=[
        {"path": ".github/workflows/yoke-ci.yml",
         "head_branch": "gh-readonly-queue/main/pr-7-abc",
         "head_sha": "a" * 40, "html_url": "https://runs/7",
         "conclusion": "success"},
    ])
    receipt, warn = receipt_mod.observe_batch(_ctx(), pr_num="42")
    assert receipt.head_sha == ""
    assert receipt.run_url == ""
    assert receipt.merge_sha == "m" * 40
    assert "no merge_group workflow run identified" in warn


def test_observe_batch_without_runs_keeps_merge_identity(monkeypatch):
    _wire_transport(monkeypatch, runs=[])
    receipt, warn = receipt_mod.observe_batch(_ctx(), pr_num="42")
    assert receipt.head_sha == ""
    assert receipt.merge_sha == "m" * 40
    assert "no merge_group workflow run" in warn


def test_record_batch_evidence_payload_shape():
    captured = {}

    def dispatch(*, function_id, target, payload, **_kw):
        captured["function_id"] = function_id
        captured["payload"] = payload
        return SimpleNamespace(success=True, result={}, error=None)

    receipt = BatchReceipt(
        pr_num="42", merge_sha="m" * 40,
        members=("YOK-300", "YOK-301"),
        head_sha="h" * 40, run_url="https://runs/42",
    )
    error = receipt_mod.record_batch_evidence(9, receipt, dispatch=dispatch)
    assert error is None
    assert captured["function_id"] == "merge.tests.record_post_rebase_ci_run"
    payload = captured["payload"]
    assert payload["verdict"] == "pass"
    assert payload["performed_by"] == "ci_run"
    raw = loads_text(payload["raw_result"])
    assert raw["verification_tree"]["head_sha"] == "h" * 40
    batch = raw["merge_queue_batch"]
    assert batch["members"] == ["YOK-300", "YOK-301"]
    assert batch["combined_head_sha"] == "h" * 40
    assert batch["run_url"] == "https://runs/42"


def test_record_batch_evidence_surfaces_dispatch_error():
    def dispatch(**_kw):
        return SimpleNamespace(
            success=False, result=None,
            error=SimpleNamespace(message="claim gate refused"),
        )

    receipt = BatchReceipt(pr_num="42")
    error = receipt_mod.record_batch_evidence(9, receipt, dispatch=dispatch)
    assert error == "claim gate refused"
