"""Queue-routed landing orchestration: admission, entry, poll, close-out."""

from types import SimpleNamespace

from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueEntryResult,
    QueueMember,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx(branch="YOK-200") -> MergeContext:
    return MergeContext(args=MergeArgs(branch=branch), project="yoke")


def _ok_response(result):
    return SimpleNamespace(success=True, result=result, error=None)


def _fail_response(message):
    return SimpleNamespace(
        success=False, result=None, error=SimpleNamespace(message=message)
    )


def _dispatch_for(shapes):
    """Dispatch fake serving claims/profile/dependency reads per item ref."""

    def dispatch(*, function_id, target, payload, **_kw):
        ref = target.item_ref
        shape = shapes.get(ref) or {}
        if function_id == "claims.path.list":
            return _ok_response({"claims": shape.get("claims", [])})
        if function_id == "items.get.run":
            return _ok_response(
                {"db_mutation_profile": shape.get("profile", "")}
            )
        if function_id == "shepherd.dependency_list.run":
            return _ok_response(
                {"dependencies": shape.get("dependencies", [])}
            )
        raise AssertionError(f"unexpected function {function_id}")

    return dispatch


def _wire_happy_path(monkeypatch, *, members=(), landing_states=None):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (list(members), None),
    )
    monkeypatch.setattr(
        route_mod, "find_existing_pr", lambda ctx: ("url", "42")
    )
    monkeypatch.setattr(
        route_mod, "enter_merge_queue",
        lambda ctx, pr_num: QueueEntryResult(success=True, pr_num=pr_num),
    )
    states = list(landing_states or [
        PrLandingState(merged=True, closed=True, auto_merge_active=False),
    ])
    # Exhausted scripts keep serving their final state: the pre-entry
    # convergence check consumes one read before the poll loop starts.
    states_last = [states[-1]]

    def landing(ctx, pr_num):
        return (states.pop(0) if states else states_last[0]), None

    monkeypatch.setattr(route_mod, "read_pr_landing_state", landing)
    monkeypatch.setattr(route_mod, "stamp_merged_at", lambda item_id: None)
    receipt = BatchReceipt(
        pr_num="42", merge_sha="m" * 40, members=("YOK-200",),
        head_sha="h" * 40, run_url="https://runs/1",
    )
    monkeypatch.setattr(
        route_mod, "observe_batch",
        lambda ctx, *, pr_num, member_snapshot: (receipt, None),
    )
    monkeypatch.setattr(
        route_mod, "record_batch_evidence",
        lambda item_id, receipt, **_kw: None,
    )
    return receipt


def test_happy_path_lands_and_records(monkeypatch):
    receipt = _wire_happy_path(monkeypatch)
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(),
        item_id=1,
        item_ref="YOK-200",
        dispatch=_dispatch_for({"YOK-200": {}}),
        sleep=lambda _s: None,
    )
    assert outcome.ok
    assert outcome.exit_code == 0
    assert outcome.pr_num == "42"
    assert outcome.batch == receipt
    assert outcome.merge_sha == receipt.merge_sha


def test_admission_refusal_is_recoverable_and_skips_pr(monkeypatch):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")], None,
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("PR machinery must not run on refusal")

    monkeypatch.setattr(route_mod, "find_existing_pr", forbidden)
    shapes = {
        "YOK-200": {"claims": [
            {"state": "active", "target_ids": [5]},
        ]},
        "YOK-150": {"claims": [
            {"state": "active", "target_ids": [5]},
        ]},
    }
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(),
        item_id=1,
        item_ref="YOK-200",
        dispatch=_dispatch_for(shapes),
        sleep=lambda _s: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "unattested-path-overlap" in outcome.error
    assert "YOK-150" in outcome.error


def test_queue_unreadable_is_named_error(monkeypatch):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (None, "no merge queue on 'main'"),
    )
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for({}), sleep=lambda _s: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "no merge queue" in outcome.error


def test_ejection_surfaces_recoverable_named_error(monkeypatch):
    _wire_happy_path(
        monkeypatch,
        landing_states=[
            PrLandingState(merged=False, closed=False, auto_merge_active=False),
        ],
    )
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for({"YOK-200": {}}), sleep=lambda _s: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "ejected" in outcome.error


def test_closed_unmerged_is_terminal(monkeypatch):
    _wire_happy_path(
        monkeypatch,
        landing_states=[
            PrLandingState(merged=False, closed=True, auto_merge_active=False),
        ],
    )
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for({"YOK-200": {}}), sleep=lambda _s: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "closed without merging" in outcome.error


def test_deadline_expiry_is_recoverable(monkeypatch):
    _wire_happy_path(
        monkeypatch,
        landing_states=[
            PrLandingState(merged=False, closed=False, auto_merge_active=True),
        ] * 100,
    )
    clock = {"now": 0.0}

    def monotonic():
        clock["now"] += 40.0
        return clock["now"]

    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for({"YOK-200": {}}),
        sleep=lambda _s: None,
        monotonic=monotonic,
        deadline_seconds=120.0,
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "did not merge within" in outcome.error


def test_serial_dependency_refuses_against_queued_member(monkeypatch):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")], None,
        ),
    )
    shapes = {
        "YOK-200": {
            "claims": [],
            "dependencies": [{
                "dependent_item": "YOK-200",
                "blocking_item": "YOK-150",
                "gate_point": "activation",
            }],
        },
        "YOK-150": {"claims": []},
    }
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for(shapes), sleep=lambda _s: None,
    )
    assert not outcome.ok
    assert "serial-ordering" in outcome.error


def test_migration_carrier_shapes_resolve_from_profile(monkeypatch):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")], None,
        ),
    )
    shapes = {
        "YOK-200": {"profile": '{"state":"declared"}'},
        "YOK-150": {"profile": '{"state":"declared"}'},
    }
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for(shapes), sleep=lambda _s: None,
    )
    assert not outcome.ok
    assert "migration-carrier-limit" in outcome.error



def test_reentry_with_merged_pr_skips_queue_entry(monkeypatch):
    _wire_happy_path(monkeypatch)

    def forbidden_entry(ctx, pr_num):
        raise AssertionError("must not re-enter an already-merged PR")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden_entry)
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for({"YOK-200": {}}), sleep=lambda _s: None,
    )
    assert outcome.ok


def test_reentry_with_armed_pr_skips_entry_and_polls(monkeypatch):
    _wire_happy_path(
        monkeypatch,
        landing_states=[
            PrLandingState(merged=False, closed=False, auto_merge_active=True),
            PrLandingState(merged=True, closed=True, auto_merge_active=False),
        ],
    )

    def forbidden_entry(ctx, pr_num):
        raise AssertionError("must not re-arm merge-when-ready")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden_entry)
    outcome = route_mod.land_item_through_merge_queue(
        _ctx(), item_id=1, item_ref="YOK-200",
        dispatch=_dispatch_for({"YOK-200": {}}), sleep=lambda _s: None,
    )
    assert outcome.ok
