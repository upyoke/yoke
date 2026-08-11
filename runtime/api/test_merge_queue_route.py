"""Queue-routed landing orchestration: admission, entry, poll, close-out."""

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    MERGED,
    UNARMED,
    dispatch_for,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.engines.merge_worktree_pr_queue import QueueMember


def test_happy_path_lands_and_records(monkeypatch):
    receipt = wire_happy_path(
        monkeypatch, landing_states=[UNARMED, ARMED, MERGED],
    )
    outcome = land()
    assert outcome.ok
    assert outcome.exit_code == 0
    assert outcome.pr_num == "42"
    assert outcome.batch == receipt
    assert outcome.merge_sha == receipt.merge_sha
    assert not outcome.already_merged
    # Carried out of the close-out because the caller writes it straight
    # into the item's execution evidence, which is refused without it.
    assert outcome.touched_files == ("a.py",)


def test_admission_refusal_is_recoverable_and_skips_pr(monkeypatch):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")], None,
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("PR machinery must not run on refusal")

    monkeypatch.setattr(route_mod, "find_landable_pull_request", forbidden)
    shapes = {
        "YOK-200": {"claims": [
            {"state": "active", "target_ids": [5]},
        ]},
        "YOK-150": {"claims": [
            {"state": "active", "target_ids": [5]},
        ]},
    }
    outcome = land(dispatch=dispatch_for(shapes))
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "unattested-path-overlap" in outcome.error
    assert "YOK-150" in outcome.error


def test_queue_unreadable_is_named_error(monkeypatch):
    monkeypatch.setattr(
        route_mod, "read_queue_members",
        lambda ctx, base_branch="main": (None, "no merge queue on 'main'"),
    )
    outcome = land(dispatch=dispatch_for({}))
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "no merge queue" in outcome.error


def test_deadline_expiry_is_recoverable(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED] * 100)
    clock = {"now": 0.0}

    def monotonic():
        clock["now"] += 40.0
        return clock["now"]

    outcome = land(monotonic=monotonic, deadline_seconds=120.0)
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
    outcome = land(dispatch=dispatch_for(shapes))
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
    outcome = land(dispatch=dispatch_for(shapes))
    assert not outcome.ok
    assert "migration-carrier-limit" in outcome.error
