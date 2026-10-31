"""The durable handoff follows GitHub's queue membership, not the arming."""

from yoke_contracts.timestamps import parse_instant
from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    UNARMED,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_route as route_mod


def test_an_unqueued_pull_request_never_reports_a_pending_handoff(monkeypatch):
    """Arming is a request; the durable marker follows GitHub's answer."""
    wire_happy_path(monkeypatch, landing_states=[UNARMED, UNARMED])
    monkeypatch.setattr(
        route_mod,
        "verify_landing_admitted",
        lambda *_a, **_k: (
            "pull request 42 was not taken by the merge queue after the "
            "merge-when-ready request: it conflicts with its base branch"
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("an unqueued landing must not mark a handoff")

    monkeypatch.setattr(route_mod, "mark_landing_pending", forbidden)

    outcome = land(wait_for_landing=False)

    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert not outcome.landing_pending
    assert "was not taken by the merge queue" in outcome.error


def test_a_red_required_check_refuses_before_merge_when_ready_is_armed(
    monkeypatch,
):
    """Arming a pull request GitHub has already refused creates the stuck wait."""
    wire_happy_path(monkeypatch, landing_states=[UNARMED, UNARMED])
    monkeypatch.setattr(
        route_mod,
        "red_entry_checks_refusal",
        lambda *_a, **_k: (
            "pull request 42 was not armed for the merge queue: its "
            "required checks already concluded red (repo-contracts=failure "
            "(https://runs/9))"
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("a red pull request must not be armed")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden)
    monkeypatch.setattr(route_mod, "mark_landing_pending", forbidden)

    outcome = land(wait_for_landing=False)

    assert not outcome.ok
    assert outcome.exit_code == 1
    assert not outcome.landing_pending
    assert "was not armed for the merge queue" in outcome.error
    assert "repo-contracts=failure" in outcome.error


def test_only_an_already_armed_retry_preserves_the_episode(monkeypatch):
    for state, preserve in ((UNARMED, False), (ARMED, True)):
        wire_happy_path(monkeypatch, landing_states=[state])
        calls = []

        def mark(item_id, pr_number, *, dispatch, preserve_existing):
            calls.append(preserve_existing)
            return parse_instant("2026-08-27T17:00:00Z"), ""

        monkeypatch.setattr(route_mod, "mark_landing_pending", mark)
        outcome = land(wait_for_landing=False)
        assert outcome.ok
        assert outcome.landing_pending
        assert calls == [preserve]


def test_unchanged_failed_train_never_dispatches_or_enters_queue(monkeypatch):
    from runtime.api.merge_queue_landing_test_helpers import LANE_SHA, dispatch_for
    from yoke_core.domain import merge_queue_failed_train as failed
    from yoke_core.engines.merge_worktree_pr_train_run import TrainRun

    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    actions, entries = [], []
    ordinary_dispatch = dispatch_for({f"YOK-{200}": {}})

    def dispatch(**kwargs):
        actions.append(kwargs["function_id"])
        return ordinary_dispatch(**kwargs)

    def guard(*args, **kwargs):
        return failed.unchanged_failed_train_refusal(
            *args,
            **kwargs,
            base_sha="b" * 40,
            parents=["b" * 40, LANE_SHA],
            train=TrainRun(
                conclusion="failure",
                head_sha="c" * 40,
                url="https://github.com/example/project/actions/runs/123",
            ),
        )

    monkeypatch.setattr(route_mod, "unchanged_failed_train_refusal", guard)
    monkeypatch.setattr(
        route_mod, "enter_merge_queue", lambda *args: entries.append(args)
    )
    result = land(dispatch=dispatch, wait_for_landing=False)
    assert not result.ok
    assert "failed-train-unchanged" in result.error
    assert "fix it on the lane" in result.error
    assert not any(action.startswith("merge_queue.") for action in actions)
    assert entries == []
