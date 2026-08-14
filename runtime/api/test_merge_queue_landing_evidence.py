"""What a queue landing is answerable for once its train has merged.

Every case here is a way the landing could record something it never
observed: a pull request bound to no lane head at all, an evidence record
emptied by an unreadable GitHub, or an ejection report carrying a run that
belongs to a different train. Each of those reads afterwards as a clean
landing, which is what makes them worth a test apiece.
"""

from runtime.api.merge_queue_landing_test_helpers import (
    CHECKOUT,
    LANE_SHA,
    UNARMED,
    ctx,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain import merge_queue_route_selection as selection_mod
from yoke_core.domain.merge_queue_route import QueueLandingOutcome
from yoke_core.domain.standalone_item_merge_receipt import MergeReceipt
from yoke_core.engines.merge_worktree_pr_rest import PrCreateResult


ALREADY_MERGED_HEAD = "b" * 40


# --- The landing carries the commit it is answerable for --------------------


def _declared(monkeypatch) -> None:
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (True, None),
    )


def _capture_queue_landing(monkeypatch) -> dict:
    seen: dict = {}

    def landing(merge_ctx, **kwargs):
        seen.update(kwargs, ctx=merge_ctx)
        return QueueLandingOutcome(
            ok=True, exit_code=0, pr_num="42",
            commit_sha=kwargs["commit_sha"], merge_sha="m" * 40,
            touched_files=("a.py",),
        )

    monkeypatch.setattr(
        selection_mod, "land_item_through_merge_queue", landing
    )
    return seen


def _route(**overrides):
    kwargs = {
        "item_id": 1,
        "branch": "YOK-200",
        "target": "main",
        "repo_root": CHECKOUT,
        "project": "yoke",
        "item_ref": "YOK-200",
    }
    kwargs.update(overrides)
    return selection_mod.route_standalone_landing(**kwargs)


def test_queue_landing_derives_the_lane_head_the_control_plane_lacks(
    monkeypatch,
):
    """An unrecorded head comes from the branch, as the local engine does.

    Handing the queue an empty one disables the guard that declines a pull
    request which merged an older head, and records a receipt naming no
    landing commit — both of which read afterwards as a clean landing.
    """
    _declared(monkeypatch)
    seen = _capture_queue_landing(monkeypatch)
    monkeypatch.setattr(
        selection_mod.git, "head_of", lambda _root, _branch: LANE_SHA
    )
    outcome = _route()
    assert outcome.ok
    assert seen["commit_sha"] == LANE_SHA
    assert outcome.commit_sha == LANE_SHA


def test_queue_landing_falls_back_to_the_receipt_once_the_lane_is_pruned(
    monkeypatch,
):
    """A landing re-entered after its own close-out still converges."""
    _declared(monkeypatch)
    seen = _capture_queue_landing(monkeypatch)
    monkeypatch.setattr(selection_mod.git, "head_of", lambda _root, _b: "")
    monkeypatch.setattr(
        selection_mod.receipts, "load",
        lambda *_a, **_kw: MergeReceipt(
            branch="YOK-200", target="main", commit_sha=LANE_SHA,
        ),
    )
    assert _route().ok
    assert seen["commit_sha"] == LANE_SHA


def test_queue_landing_refuses_when_no_lane_head_resolves(monkeypatch):
    """Nothing reaches the queue without the commit it would be evidence for."""
    _declared(monkeypatch)

    def forbidden(*_a, **_kw):
        raise AssertionError("a landing with no lane head must not be queued")

    monkeypatch.setattr(
        selection_mod, "land_item_through_merge_queue", forbidden
    )
    monkeypatch.setattr(selection_mod.git, "head_of", lambda _root, _b: "")
    monkeypatch.setattr(selection_mod.receipts, "load", lambda *_a, **_kw: None)
    outcome = _route()
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "no lane head" in outcome.error
    assert "YOK-200" in outcome.error


def test_the_lane_head_is_what_declines_a_stale_merged_pull_request(
    monkeypatch,
):
    """The guard is only a guard when the landing hands it a real head."""
    seen: dict = {}

    def lookup(_ctx, lane_head=""):
        seen["lane_head"] = lane_head
        return None, None, (
            f"pull request 7 merged head {ALREADY_MERGED_HEAD[:12]}, not the "
            f"lane head {lane_head[:12]}"
        )

    monkeypatch.setattr(landing_pr_mod, "find_landable_pull_request", lookup)
    monkeypatch.setattr(
        landing_pr_mod, "create_pr",
        lambda _ctx, *, title, body: PrCreateResult(
            pr_url="", pr_num="", already_exists=True,
        ),
    )
    pr_num, error = landing_pr_mod.ensure_landing_pull_request(
        ctx(), "YOK-200", lane_head=LANE_SHA,
    )
    assert pr_num == ""
    assert seen["lane_head"] == LANE_SHA
    assert "carries commits beyond the pull request that merged it" in error


# --- An unreadable GitHub does not empty the evidence record ----------------


def _wire_close_out(monkeypatch, *, pr_files) -> dict:
    """Wire one close-out; return what its receipt recorded."""
    recorded: dict = {}
    monkeypatch.setattr(close_out_mod, "stamp_merged_at", lambda _item: None)
    monkeypatch.setattr(
        close_out_mod, "observe_batch",
        lambda _ctx, *, pr_num, member_snapshot: (None, None),
    )
    monkeypatch.setattr(
        close_out_mod, "read_pr_changed_files", lambda _ctx, _pr: pr_files
    )
    monkeypatch.setattr(
        close_out_mod.receipts, "record",
        lambda item_id, receipt, **_kw: recorded.update(receipt=receipt) or "",
    )
    monkeypatch.setattr(
        close_out_mod, "fast_forward_main_checkout", lambda *_a: ""
    )
    return recorded


def _close_out(monkeypatch):
    return close_out_mod.record_landing(
        ctx(repo_root=CHECKOUT), item_id=1, commit_sha=LANE_SHA, pr_num="42",
    )


def test_close_out_reads_the_merge_when_the_pull_request_cannot_be_read(
    monkeypatch,
):
    """A landed merge whose file set is unreadable must not strand the item."""
    recorded = _wire_close_out(
        monkeypatch, pr_files=(None, "github graphql refused")
    )
    monkeypatch.setattr(close_out_mod.git, "fetch_target", lambda *_a: None)
    monkeypatch.setattr(
        close_out_mod.receipts, "touched_files_from_merge_commit",
        lambda _root, target, sha: ("a.py", "docs/b.md"),
    )
    result = _close_out(monkeypatch)
    assert result.touched_files == ("a.py", "docs/b.md")
    assert recorded["receipt"].touched_files == ("a.py", "docs/b.md")
    assert any("github graphql refused" in note for note in result.warnings)
    assert any("merge that landed" in note for note in result.warnings)


def test_close_out_reads_the_merge_against_the_remote_base_branch(monkeypatch):
    """The merge happened on GitHub, so this checkout need not have it yet."""
    _wire_close_out(monkeypatch, pr_files=(None, "github graphql refused"))
    fetched: list = []
    asked: dict = {}
    monkeypatch.setattr(
        close_out_mod.git, "fetch_target",
        lambda root, target: fetched.append((root, target)),
    )
    monkeypatch.setattr(
        close_out_mod.receipts, "touched_files_from_merge_commit",
        lambda _root, target, sha: asked.update(target=target, sha=sha)
        or ("a.py",),
    )
    _close_out(monkeypatch)
    assert fetched == [(CHECKOUT, "main")]
    assert asked == {"target": "origin/main", "sha": LANE_SHA}


def test_close_out_keeps_the_pull_requests_answer_when_it_has_one(monkeypatch):
    """The merge is the second source, read only when the first cannot be."""
    _wire_close_out(monkeypatch, pr_files=(("a.py",), None))

    def forbidden(*_a, **_kw):
        raise AssertionError("the merge is read only when the request is not")

    monkeypatch.setattr(
        close_out_mod.receipts, "touched_files_from_merge_commit", forbidden
    )
    assert _close_out(monkeypatch).touched_files == ("a.py",)


# --- An unidentified run is never another train's run -----------------------


def test_a_landing_with_no_identified_run_says_so(monkeypatch):
    """No marker match reads as unidentified, never as somebody else's green."""
    wire_happy_path(
        monkeypatch, landing_states=[UNARMED, UNARMED], queue_entries=(),
    )
    monkeypatch.setattr(
        verdict_mod, "read_train_run",
        lambda _ctx, pr_num: (
            None,
            f"no merge_group workflow run identified for pull request {pr_num}",
        ),
    )
    outcome = land()
    assert not outcome.ok
    assert "train-run=not identified" in outcome.error
    assert any(
        "no merge_group workflow run identified" in note
        for note in outcome.warnings
    )
