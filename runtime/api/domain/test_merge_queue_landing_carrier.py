"""The landing marker must name the pull request that carried the merge.

A lane whose commits reach the base under a sibling pull request leaves its
own one open, so the marker an item last armed can name a pull request that
never merged. Close-out knows the merge the base actually holds; these cover
it repointing the marker at the pull request that merge carried.
"""

from types import SimpleNamespace

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain import merge_queue_landing_carrier as carrier_mod
from yoke_core.domain.gh_rest_transport_errors import RestTransportError
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

LANE_SHA = "1" * 40
LANDING_SHA = "a" * 40
TEST_MERGE_SHA = "b" * 40
OWN_PR = "1269"
CARRIER_PR = "1251"


def _ctx(repo_root: str = "/repo") -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-3203", target="main"),
        repo_root=repo_root,
        project="yoke",
    )


def _wire_carrier(
    monkeypatch,
    *,
    listing=(),
    subject="",
    auth_error=None,
    transport_error="",
):
    """Serve the commit's pull-request listing and the marker write."""
    monkeypatch.setattr(
        carrier_mod,
        "resolve_auth_detail",
        lambda ctx, perms: (
            (None, auth_error)
            if auth_error
            else (SimpleNamespace(token="tok", repo="upyoke/yoke"), None)
        ),
    )

    def fake_request(req, *, token, **_kw):
        assert req.path == f"/repos/upyoke/yoke/commits/{LANDING_SHA}/pulls"
        if transport_error:
            raise RestTransportError(transport_error)
        return RestResponse(status=200, headers={}, body=list(listing))

    monkeypatch.setattr(carrier_mod, "request_with_retry", fake_request)
    monkeypatch.setattr(
        carrier_mod.git, "git_out", lambda _root, *_args: subject
    )
    written: list[tuple[int, str]] = []

    def record(item_id, pr_number):
        written.append((int(item_id), str(pr_number)))
        return ""

    monkeypatch.setattr(carrier_mod, "record_landing_pull_request", record)
    return written


def _sibling_listing():
    """What GitHub lists for a merge a sibling pull request performed.

    The item's own pull request is listed too — its head branch holds the
    commit — and still offers the test-merge sha GitHub keeps for an open
    pull request.
    """
    return [
        {"number": int(OWN_PR), "merge_commit_sha": TEST_MERGE_SHA},
        {"number": int(CARRIER_PR), "merge_commit_sha": LANDING_SHA},
    ]


def test_marker_is_repointed_at_the_pull_request_that_merged(monkeypatch):
    written = _wire_carrier(monkeypatch, listing=_sibling_listing())

    note = carrier_mod.repoint_to_landing_carrier(
        _ctx(),
        item_id=7,
        recorded_pr_number=OWN_PR,
        merge_sha=LANDING_SHA,
    )

    assert written == [(7, CARRIER_PR)]
    assert f"repointed from {OWN_PR} to {CARRIER_PR}" in note


def test_marker_already_naming_the_carrier_is_left_alone(monkeypatch):
    """The ordinary landing: the item's own pull request is the carrier."""
    written = _wire_carrier(
        monkeypatch,
        listing=[{"number": int(OWN_PR), "merge_commit_sha": LANDING_SHA}],
    )

    note = carrier_mod.repoint_to_landing_carrier(
        _ctx(),
        item_id=7,
        recorded_pr_number=OWN_PR,
        merge_sha=LANDING_SHA,
    )

    assert written == []
    assert note == ""


def test_a_pull_request_that_only_contains_the_merge_is_not_the_carrier(
    monkeypatch,
):
    """Association is not carriage, and the subject settles it instead."""
    written = _wire_carrier(
        monkeypatch,
        listing=[{"number": 1300, "merge_commit_sha": TEST_MERGE_SHA}],
        subject=f"Merge pull request #{CARRIER_PR} from upyoke/YOK-3226",
    )

    note = carrier_mod.repoint_to_landing_carrier(
        _ctx(),
        item_id=7,
        recorded_pr_number=OWN_PR,
        merge_sha=LANDING_SHA,
    )

    assert written == [(7, CARRIER_PR)]
    assert "subject GitHub wrote" in note


def test_merge_subject_answers_when_the_provider_cannot(monkeypatch):
    written = _wire_carrier(
        monkeypatch,
        transport_error="503 from GitHub",
        subject=f"Merge pull request #{CARRIER_PR} from upyoke/YOK-3226",
    )

    note = carrier_mod.repoint_to_landing_carrier(
        _ctx(),
        item_id=7,
        recorded_pr_number=OWN_PR,
        merge_sha=LANDING_SHA,
    )

    assert written == [(7, CARRIER_PR)]
    assert "503 from GitHub" in note


def test_unresolved_carrier_keeps_the_marker_and_names_the_repair(monkeypatch):
    """Nothing here may unwind a landing, so an unread carrier is reported."""
    written = _wire_carrier(monkeypatch, transport_error="503 from GitHub")

    note = carrier_mod.repoint_to_landing_carrier(
        _ctx(),
        item_id=7,
        recorded_pr_number=OWN_PR,
        merge_sha=LANDING_SHA,
    )

    assert written == []
    assert "landing pull request not verified" in note
    assert "operator-correct" in note


def test_a_failed_repoint_write_names_the_carrier_it_could_not_record(
    monkeypatch,
):
    _wire_carrier(monkeypatch, listing=_sibling_listing())
    monkeypatch.setattr(
        carrier_mod,
        "record_landing_pull_request",
        lambda _item_id, _pr: "control plane unreachable",
    )

    note = carrier_mod.repoint_to_landing_carrier(
        _ctx(),
        item_id=7,
        recorded_pr_number=OWN_PR,
        merge_sha=LANDING_SHA,
    )

    assert "control plane unreachable" in note
    assert CARRIER_PR in note


def _wire_close_out(monkeypatch, *, landing_sha: str):
    """Everything close-out reaches outside the repoint under test."""
    batch = BatchReceipt(
        pr_num=OWN_PR,
        merge_sha=landing_sha,
        head_sha="h" * 40,
        run_url="https://runs/42",
    )
    monkeypatch.setattr(
        close_out_mod, "read_recorded_batch", lambda item_id, *, pr_num: batch
    )
    monkeypatch.setattr(close_out_mod.git, "fetch_target", lambda *_a: None)
    monkeypatch.setattr(
        close_out_mod.receipts,
        "landing_merge_commit",
        lambda *_a: landing_sha,
    )
    monkeypatch.setattr(
        close_out_mod, "stamp_merged_at", lambda item_id, **_kw: None
    )
    monkeypatch.setattr(
        close_out_mod, "read_pr_changed_files", lambda ctx, pr_num: (("a.py",), None)
    )
    monkeypatch.setattr(close_out_mod.receipts, "record", lambda *_a, **_kw: "")
    monkeypatch.setattr(
        close_out_mod, "fast_forward_main_checkout", lambda *_a: ""
    )


def test_close_out_records_the_pull_request_that_landed(monkeypatch):
    """The reported defect: close-out left the marker on an open sibling."""
    _wire_close_out(monkeypatch, landing_sha=LANDING_SHA)
    written = _wire_carrier(monkeypatch, listing=_sibling_listing())

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num=OWN_PR,
    )

    assert written == [(7, CARRIER_PR)]
    assert any(
        f"repointed from {OWN_PR} to {CARRIER_PR}" in warning
        for warning in outcome.warnings
    )


def test_close_out_leaves_a_marker_that_already_names_the_landing(monkeypatch):
    _wire_close_out(monkeypatch, landing_sha=LANDING_SHA)
    written = _wire_carrier(
        monkeypatch,
        listing=[{"number": int(OWN_PR), "merge_commit_sha": LANDING_SHA}],
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num=OWN_PR,
    )

    assert written == []
    assert outcome.warnings == ()
