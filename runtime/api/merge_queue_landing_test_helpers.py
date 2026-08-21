"""Shared wiring for the queue-routed landing tests.

One landing exercises four collaborators — queue membership, pull-request
discovery, the pull request's own state, and the close-out — so the tests
that cover admission and the tests that cover convergence wire the same
fakes. Both readers of pull-request state share one scripted sequence,
because call order across them is exactly what the convergence rules are
about.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.item_ref import parse_public_item_ref
from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueEntryResult,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


LANE_SHA = "1" * 40

#: Where a landing that retires its own lane believes the checkout is. A
#: context without one belongs to a caller with no local checkout at all,
#: which is a different path through the close-out.
CHECKOUT = "/tmp/repo"

#: The claim a landing holds throughout its poll, which is what the
#: timeout message reports when the poll budget runs out.
HELD_BY_THIS_SESSION = {"claim_id": 77, "session_id": "sess-1"}

ARMED = PrLandingState(merged=False, closed=False, auto_merge_active=True)
UNARMED = PrLandingState(merged=False, closed=False, auto_merge_active=False)
MERGED = PrLandingState(merged=True, closed=True, auto_merge_active=False)
CLOSED = PrLandingState(merged=False, closed=True, auto_merge_active=False)


def ctx(branch: str = "YOK-200", *, repo_root: str = "") -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch=branch), repo_root=repo_root, project="yoke"
    )


def ok_response(result):
    return SimpleNamespace(success=True, result=result, error=None)


def dispatch_for(shapes, *, holder=HELD_BY_THIS_SESSION):
    """Dispatch fake serving claims/profile/dependency reads per item ref.

    ``holder`` answers the work-claim lookup the timeout message makes;
    it is keyed by item id rather than ref, so it is served before the
    per-ref shapes are consulted. Pass ``None`` for an item whose claim
    has been released.
    """

    def dispatch(*, function_id, target, payload=None, **_kw):
        if function_id == "claims.work.holder_get":
            return ok_response({"holder": holder})
        if function_id == DB_READ_FUNCTION_ID:
            rows = []
            for item_ref, shape in shapes.items():
                prefix, sequence = parse_public_item_ref(item_ref)
                if prefix is None or sequence is None:
                    continue
                rows.append(
                    [
                        shape.get("branch", item_ref),
                        shape.get("item_id", sequence),
                        shape.get("project", "yoke"),
                        prefix,
                        sequence,
                    ]
                )
            return ok_response(
                {
                    "columns": [
                        "branch",
                        "item_id",
                        "project_slug",
                        "public_item_prefix",
                        "project_sequence",
                    ],
                    "rows": rows,
                    "row_count": len(rows),
                    "row_cap": 100,
                    "truncated": False,
                    "statement_timeout_ms": 5000,
                }
            )
        ref = target.item_ref
        shape = shapes.get(ref) or {}
        if function_id == "claims.path.list":
            return ok_response({"claims": shape.get("claims", [])})
        if function_id == "items.get.run":
            return ok_response({
                "item_id": 0,
                "fields": {"db_mutation_profile": shape.get("profile", "")},
            })
        if function_id == "shepherd.dependency_list.run":
            return ok_response({
                "item_id": 0,
                "dependencies": list(shape.get("dependencies") or []),
            })
        raise AssertionError(f"unexpected function {function_id}")

    return dispatch


def wire_happy_path(
    monkeypatch,
    *,
    members=(),
    landing_states=None,
    queue_entries=(),
    train=None,
) -> BatchReceipt:
    """Wire every collaborator a landing touches; return the batch receipt."""
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda _ctx, base_branch="main": (list(members), None),
    )
    monkeypatch.setattr(
        verdict_mod, "read_queue_members",
        lambda _ctx, base_branch="main": (list(queue_entries), None),
    )
    monkeypatch.setattr(
        verdict_mod, "read_train_run", lambda _ctx, pr_num: (train, None)
    )
    monkeypatch.setattr(
        verdict_mod, "read_landing_checks",
        lambda _ctx, _sha: ((), None),
    )
    monkeypatch.setattr(
        landing_pr_mod, "find_landable_pull_request",
        lambda _ctx, lane_head="": ("url", "42", ""),
    )
    monkeypatch.setattr(
        landing_pr_mod, "read_pr_landing_state",
        lambda _ctx, _pr: (UNARMED, None),
    )
    monkeypatch.setattr(
        route_mod, "unchanged_failed_train_refusal",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        route_mod, "enter_merge_queue",
        lambda _ctx, pr_num: QueueEntryResult(success=True, pr_num=pr_num),
    )
    states = list(landing_states or [MERGED])
    # One script feeds both readers in call order: the route's pre-entry
    # convergence check, then every read the verdict takes. An exhausted
    # script keeps serving its final state.
    states_last = [states[-1]]

    def landing(_ctx, pr_num):
        return (states.pop(0) if states else states_last[0]), None

    monkeypatch.setattr(route_mod, "read_pr_landing_state", landing)
    monkeypatch.setattr(verdict_mod, "read_pr_landing_state", landing)
    monkeypatch.setattr(close_out_mod, "stamp_merged_at", lambda item_id: None)
    receipt = BatchReceipt(
        pr_num="42", merge_sha="m" * 40, members=("YOK-200",),
        head_sha="h" * 40, run_url="https://runs/1",
    )
    monkeypatch.setattr(
        close_out_mod, "observe_batch",
        lambda _ctx, *, pr_num, member_snapshot: (receipt, None),
    )
    monkeypatch.setattr(
        close_out_mod, "record_batch_evidence",
        lambda item_id, receipt, **_kw: None,
    )
    monkeypatch.setattr(
        close_out_mod, "read_pr_changed_files",
        lambda _ctx, pr_num: (("a.py",), None),
    )
    monkeypatch.setattr(
        close_out_mod.receipts, "record",
        lambda item_id, receipt, **_kw: "",
    )
    return receipt


def land(**overrides):
    """Run one landing with the defaults every test starts from."""
    kwargs = {
        "item_id": 1,
        "item_ref": "YOK-200",
        "commit_sha": LANE_SHA,
        "dispatch": dispatch_for({"YOK-200": {}}),
        "sleep": lambda _s: None,
    }
    kwargs.update(overrides)
    merge_ctx = kwargs.pop("ctx", None) or ctx()
    return route_mod.land_item_through_merge_queue(merge_ctx, **kwargs)


__all__ = [
    "ARMED",
    "CHECKOUT",
    "CLOSED",
    "HELD_BY_THIS_SESSION",
    "LANE_SHA",
    "MERGED",
    "UNARMED",
    "ctx",
    "dispatch_for",
    "land",
    "ok_response",
    "wire_happy_path",
]
