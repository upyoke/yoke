"""Shared wiring for queue admission, server-record wait, and close-out."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.public_ref import parse_public_item_ref
from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_landing_wait as wait_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.merge_queue_landing_record_state import LANDED
from yoke_core.domain.merge_queue_readiness import (
    ENQUEUED,
    MERGE_WHEN_READY_CONSUMED,
)
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
#: timeout message reports when the record wait budget runs out.
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


def landing_record(
    state=LANDED,
    *,
    pr_number="42",
    narrative="pull request 42: merged=true",
    head_sha="",
    failed_checks=(),
    disarm_note="",
    observed_at="2026-09-04T01:00:00Z",
    queue_holding=ENQUEUED,
    queue_entry_state="AWAITING_CHECKS",
    merge_when_ready=MERGE_WHEN_READY_CONSUMED,
):
    """One server record returned to a waiting lane."""
    return {
        "item_id": 1,
        "project_id": 1,
        "pr_number": str(pr_number),
        "state": state,
        "head_sha": head_sha,
        "queue_holding": queue_holding,
        "queue_entry_state": queue_entry_state,
        "merge_when_ready": merge_when_ready,
        "failed_checks": [
            {
                "name": check.name,
                "status": check.status,
                "conclusion": check.conclusion,
                "required": check.required,
                "url": check.url,
            }
            for check in failed_checks
        ],
        "narrative": narrative,
        "disarm_note": disarm_note,
        "observed_at": observed_at,
        "changed_at": observed_at,
    }


def dispatch_for(
    shapes,
    *,
    holder=HELD_BY_THIS_SESSION,
    merge_queue=None,
    landing_records=None,
    landing_stale=False,
):
    """Dispatch fake serving claims/profile/dependency reads per item ref.

    ``holder`` answers the work-claim lookup the timeout message makes;
    it is keyed by item id rather than ref, so it is served before the
    per-ref shapes are consulted. Pass ``None`` for an item whose claim
    has been released.

    ``merge_queue`` is the item's recorded landing, which the route reads
    before anything else: an empty one means no landing is on record, so
    the full landing path runs.
    """

    records = list([landing_record()] if landing_records is None else landing_records)
    last_record = [records[-1] if records else None]

    def dispatch(*, function_id, target, payload=None, **_kw):
        if function_id == "claims.work.holder_get":
            return ok_response({"holder": holder})
        if function_id == "items.detail.get":
            return ok_response({"item": {"merge_queue": dict(merge_queue or {})}})
        if function_id == "merge_queue.landing_pending.mark":
            return ok_response(
                {
                    "item_id": 1,
                    "pr_number": str((payload or {}).get("pr_number") or "42"),
                    "enqueued_at": str((payload or {}).get("enqueued_at") or ""),
                    "landed_at": "",
                    "notified_at": "",
                }
            )
        if function_id == wait_mod.OBSERVE_FUNCTION_ID:
            record = records.pop(0) if records else last_record[0]
            last_record[0] = record
            observed_at = str((record or {}).get("observed_at") or "")
            return ok_response(
                {
                    "item_id": 1,
                    "project_id": 1,
                    "refreshed": True,
                    "stale": bool(landing_stale),
                    "age_seconds": 0.0,
                    "stale_after_seconds": 120.0,
                    "record": record,
                    "refresh": {
                        "project_id": 1,
                        "started_at": observed_at,
                        "completed_at": observed_at,
                        "last_error": "",
                        "in_progress": False,
                    },
                }
            )
        if function_id == DB_READ_FUNCTION_ID:
            rows = []
            for public_ref, shape in shapes.items():
                prefix, sequence = parse_public_item_ref(public_ref)
                if prefix is None or sequence is None:
                    continue
                rows.append(
                    [
                        shape.get("branch", public_ref),
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
        ref = target.public_ref
        shape = shapes.get(ref) or {}
        if function_id == "claims.path.list":
            return ok_response({"claims": shape.get("claims", [])})
        if function_id == "items.get.run":
            return ok_response(
                {
                    "item_id": 0,
                    "fields": {"db_mutation_profile": shape.get("profile", "")},
                }
            )
        if function_id == "items.dependency.list":
            return ok_response(
                {
                    "item_id": 0,
                    "dependencies": list(shape.get("dependencies") or []),
                }
            )
        raise AssertionError(f"unexpected function {function_id}")

    return dispatch


def wire_happy_path(
    monkeypatch,
    *,
    members=(),
    landing_states=None,
) -> BatchReceipt:
    """Wire every collaborator a landing touches; return the batch receipt."""
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda _ctx, base_branch="main": (list(members), None),
    )
    # Nothing red before the arm is the default; the ordering cases say so
    # for themselves.
    monkeypatch.setattr(
        route_mod,
        "red_entry_checks_refusal",
        lambda *_a, **_k: "",
    )
    monkeypatch.setattr(
        landing_pr_mod,
        "find_landable_pull_request",
        lambda _ctx, lane_head="": ("url", "42", ""),
    )
    monkeypatch.setattr(
        landing_pr_mod,
        "read_pr_landing_state",
        lambda _ctx, _pr: (UNARMED, None),
    )
    monkeypatch.setattr(
        route_mod,
        "unchanged_failed_train_refusal",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        route_mod,
        "enter_merge_queue",
        lambda _ctx, pr_num: QueueEntryResult(success=True, pr_num=pr_num),
    )
    # GitHub holding the landing is the default these tests assume; the
    # cases about a queue that did not take it override this explicitly.
    monkeypatch.setattr(
        route_mod,
        "verify_landing_admitted",
        lambda *_a, **_k: "",
    )
    states = list(landing_states or [MERGED])
    # The route reads GitHub once before arming. Waiting then crosses only
    # the registered server-record boundary, supplied by ``dispatch_for``.
    states_last = [states[-1]]

    def landing(_ctx, pr_num):
        return (states.pop(0) if states else states_last[0]), None

    monkeypatch.setattr(route_mod, "read_pr_landing_state", landing)
    monkeypatch.setattr(close_out_mod, "stamp_merged_at", lambda item_id: None)
    receipt = BatchReceipt(
        pr_num="42",
        merge_sha="m" * 40,
        members=("YOK-200",),
        head_sha="h" * 40,
        run_url="https://runs/1",
    )
    monkeypatch.setattr(
        close_out_mod,
        "observe_batch",
        lambda _ctx, *, pr_num, member_snapshot, drift_check=None: (
            receipt,
            None,
        ),
    )
    monkeypatch.setattr(
        close_out_mod,
        "record_batch_evidence",
        lambda item_id, receipt, **_kw: None,
    )
    monkeypatch.setattr(
        close_out_mod,
        "read_pr_changed_files",
        lambda _ctx, pr_num: (("a.py",), None),
    )
    monkeypatch.setattr(
        close_out_mod.receipts,
        "record",
        lambda item_id, receipt, **_kw: "",
    )
    return receipt


def land(**overrides):
    """Run one landing with the defaults every test starts from."""
    landing_records = overrides.pop("landing_records", None)
    landing_stale = overrides.pop("landing_stale", False)
    kwargs = {
        "item_id": 1,
        "public_ref": "YOK-200",
        "commit_sha": LANE_SHA,
        "dispatch": dispatch_for(
            {"YOK-200": {}},
            landing_records=landing_records,
            landing_stale=landing_stale,
        ),
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
    "landing_record",
    "ok_response",
    "wire_happy_path",
]
