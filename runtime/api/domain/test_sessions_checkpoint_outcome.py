"""Checkpoint adapter classifies outcomes and returns the chain label."""

from __future__ import annotations

from yoke_core.domain.sessions_handler_outcome import (
    OUTCOME_BLOCKED,
    OUTCOME_COMPLETED,
    OUTCOME_RECOVERABLE_SUBSTRATE,
    OUTCOME_SLICE_COMMITTED,
    OUTCOME_TERMINAL_ITEM_CLOSED,
    render_chain_summary_label,
    resolve_checkpoint_outcome,
    resolved_checkpoint_chainable,
)


def test_resolve_keeps_pre_dispatch_literal():
    assert (
        resolve_checkpoint_outcome(
            outcome="pre-dispatch",
            required_path="advance",
            pre_status="implementing",
            post_status="implementing",
        )
        == "pre-dispatch"
    )


def test_resolve_classifies_advance_slice_from_statuses():
    assert (
        resolve_checkpoint_outcome(
            required_path="advance",
            pre_status="implementing",
            post_status="implementing",
        )
        == OUTCOME_SLICE_COMMITTED
    )


def test_resolve_classifies_advance_boundary_as_completed():
    assert (
        resolve_checkpoint_outcome(
            required_path="advance",
            pre_status="implementing",
            post_status="reviewing-implementation",
        )
        == OUTCOME_COMPLETED
    )


def test_resolve_failure_class_beats_advance_path():
    assert (
        resolve_checkpoint_outcome(
            failure_class="dirty-tracked-main",
            required_path="advance",
            pre_status="idea",
            post_status="idea",
        )
        == OUTCOME_RECOVERABLE_SUBSTRATE
    )


def test_resolve_unknown_failure_class_is_blocked():
    assert (
        resolve_checkpoint_outcome(
            failure_class="never-seen-before-class",
        )
        == OUTCOME_BLOCKED
    )


def test_resolved_chainable_false_on_blocked():
    assert resolved_checkpoint_chainable(True, OUTCOME_BLOCKED) is False
    assert resolved_checkpoint_chainable(True, OUTCOME_COMPLETED) is True


def test_non_completed_label_is_not_handler_completed():
    slice_label = render_chain_summary_label(OUTCOME_SLICE_COMMITTED)
    assert slice_label != "handler completed"
    assert "slice" in slice_label


def test_terminal_item_label_names_consumed_checkpoint():
    label = render_chain_summary_label(OUTCOME_TERMINAL_ITEM_CLOSED)
    assert label == "terminal item closed; checkpoint consumed"
