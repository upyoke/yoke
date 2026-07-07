"""Charge-context regressions for ``apply_process_offer_gate``.

Covers the scheduler routing-context preservation contract for the
disabled-process CHARGE swap path:

- AC-1 / AC-12: when the gate rewrites a disabled process action into
  ``ActionKind.CHARGE`` and ``FrontierState.scheduler_context`` is
  present, the returned context includes a ``scheduler`` block.
- AC-2: skipped-process metadata stays additive on the same charge
  context (process_key, config_key, recommended_action, skip_reason,
  original_reason, direct_command).
- AC-3: the normal charge path and the fallback path emit aligned
  context shapes when scheduler context is available -- both build
  from :func:`build_charge_context`.
- AC-4: regression for disabled FEED with assignable runnable work.
- AC-5: regression for disabled STRATEGIZE with assignable runnable
  work.
- AC-7: no-runnable disabled-process path returns suppressed-WAIT
  and does not invent scheduler context.
- AC-8: explicit branch coverage for the assignable-runnable +
  no-scheduler-context case (backward-compat non-scheduler charge
  shape that ``/yoke do`` will not dispatch).
- AC-11: when the fallback attaches scheduler context, ``selected_item``
  matches the scheduler-selected item rather than ``runnable_items[0]``.

The skip-memory recording side-effect lives in
``test_session_decision_process_skip_recording``; this file exercises
only the pure decision-context shape returned by
:func:`apply_process_offer_gate`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session_contract import (
    ActionKind,
    FrontierState,
    NextAction,
)
from yoke_core.domain.session_decision_charge import (
    build_charge_context,
    decide_charge_action,
)
from yoke_core.domain.session_decision_process_gate import (
    apply_process_offer_gate,
)
from yoke_core.api.routing_config import ProcessOfferPolicy


RUNNABLE_PRIMARY_ID = 1700
RUNNABLE_SECONDARY_ID = 1701
RUNNABLE_PRIMARY = f"YOK-{RUNNABLE_PRIMARY_ID}"
RUNNABLE_SECONDARY = f"YOK-{RUNNABLE_SECONDARY_ID}"


def _scheduler_block(item_id: str) -> dict:
    return {
        "next_step": "advance",
        "item_type": "issue",
        "status": "refined-idea",
        "title": f"runnable {item_id}",
        "rank": 1,
        "explanation": f"Ranked #1: advance for issue in refined-idea ({item_id})",
        "adapter": "conduct",
    }


def _scheduler_frontier(
    *,
    selected_item: str = RUNNABLE_PRIMARY,
    runnable_items: list[str] | None = None,
) -> FrontierState:
    """Frontier where the scheduler selected ``selected_item``."""
    items = runnable_items if runnable_items is not None else [
        selected_item, RUNNABLE_SECONDARY,
    ]
    return FrontierState(
        sml_coherent=True,
        runnable_items=list(items),
        selected_item=selected_item,
        scheduler_context=_scheduler_block(selected_item),
    )


def _make_action(kind: ActionKind, reason: str = "") -> NextAction:
    return NextAction(
        action=kind,
        reason=reason or f"{kind.value} test",
        chainable=False,
        correlation_id="charge-ctx-sess",
        context={},
    )


class TestSchedulerContextPreserved:
    """AC-1 / AC-4 / AC-5 / AC-12."""

    def test_disabled_feed_with_scheduler_context_charge_carries_scheduler(self):
        action = _make_action(
            ActionKind.FEED,
            reason="Drift review: frontier impacted. summary",
        )
        frontier = _scheduler_frontier()
        policy = ProcessOfferPolicy()  # default disabled
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.CHARGE
        assert result.chainable is True
        scheduler = result.context["scheduler"]
        assert scheduler["next_step"] == "advance"
        assert scheduler["status"] == "refined-idea"
        assert scheduler["item_type"] == "issue"
        assert scheduler["title"] == f"runnable {RUNNABLE_PRIMARY}"
        assert scheduler["rank"] == 1
        assert scheduler["adapter"] == "conduct"
        assert "explanation" in scheduler

    def test_disabled_strategize_with_scheduler_context_charge_carries_scheduler(self):
        action = _make_action(ActionKind.STRATEGIZE)
        frontier = _scheduler_frontier()
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.CHARGE
        assert result.context["scheduler"]["next_step"] == "advance"

    def test_skipped_process_fields_remain_additive_on_charge(self):
        # skipped_process keys are present alongside scheduler.
        action = _make_action(
            ActionKind.FEED,
            reason="Drift review: frontier impacted. 2 delivered item(s).",
        )
        frontier = _scheduler_frontier()
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        skipped = result.context["skipped_process"]
        assert skipped["process_key"] == "FEED"
        assert skipped["config_key"] == "do_process_offer_feed"
        assert skipped["recommended_action"] == "feed"
        assert skipped["skip_reason"] == "process_disabled_by_config"
        assert skipped["original_reason"].startswith("Drift review")
        assert skipped["direct_command"] == "/yoke feed"

    def test_residue_no_charge_with_scheduler_available_omits_scheduler(self):
        # When frontier.scheduler_context is set and the gate
        # returns CHARGE, the result must include the scheduler block.
        action = _make_action(ActionKind.FEED)
        frontier = _scheduler_frontier()
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.CHARGE
        assert "scheduler" in result.context
        assert result.context["scheduler"].get("next_step")


class TestSelectedItemAlignment:
    """AC-11: selected_item matches scheduler-selected item."""

    def test_selected_item_uses_frontier_selected_item_not_first_runnable(self):
        # The scheduler picked RUNNABLE_PRIMARY but listed
        # RUNNABLE_SECONDARY first in runnable_items. The fallback must
        # honour scheduler.selected_item, not runnable_items[0].
        frontier = FrontierState(
            sml_coherent=True,
            runnable_items=[RUNNABLE_SECONDARY, RUNNABLE_PRIMARY],
            selected_item=RUNNABLE_PRIMARY,
            scheduler_context=_scheduler_block(RUNNABLE_PRIMARY),
        )
        action = _make_action(ActionKind.FEED)
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.context["selected_item"] == RUNNABLE_PRIMARY
        # The scheduler-block reflects the same selected item.
        assert result.context["scheduler"]["title"] == f"runnable {RUNNABLE_PRIMARY}"
        assert RUNNABLE_PRIMARY in result.reason


class TestSharedHelperShape:
    """AC-3: normal charge and fallback charge use the same helper."""

    def test_build_charge_context_returns_scheduler_when_available(self):
        frontier = _scheduler_frontier()
        ctx = build_charge_context(frontier)
        assert ctx["selected_item"] == RUNNABLE_PRIMARY
        assert ctx["runnable_items"] == [RUNNABLE_PRIMARY, RUNNABLE_SECONDARY]
        assert ctx["scheduler"]["next_step"] == "advance"

    def test_build_charge_context_omits_scheduler_when_absent(self):
        frontier = FrontierState(
            sml_coherent=True,
            runnable_items=[RUNNABLE_PRIMARY],
            selected_item=RUNNABLE_PRIMARY,
            scheduler_context=None,
        )
        ctx = build_charge_context(frontier)
        assert ctx["selected_item"] == RUNNABLE_PRIMARY
        assert ctx["runnable_items"] == [RUNNABLE_PRIMARY]
        assert "scheduler" not in ctx

    def test_normal_and_fallback_charge_share_scheduler_shape(self):
        # Both code paths should produce the same scheduler keys for the
        # same frontier — no drift.
        frontier = _scheduler_frontier()

        normal_action = decide_charge_action(
            offer=_dummy_offer(), frontier=frontier,
            correlation="corr", lane_allowed_paths=None,
        )
        assert normal_action is not None
        gate_action = apply_process_offer_gate(
            _make_action(ActionKind.FEED), frontier, "corr",
            ProcessOfferPolicy(),
        )

        normal_keys = sorted(normal_action.context.get("scheduler", {}).keys())
        gate_keys = sorted(gate_action.context.get("scheduler", {}).keys())
        assert normal_keys == gate_keys
        assert normal_action.context["scheduler"] == gate_action.context["scheduler"]


class TestNoRunnableSuppressedWait:
    """AC-7: no-runnable + disabled process returns suppressed-WAIT (non-terminal)."""

    def test_disabled_feed_no_runnable_returns_suppressed_wait(self):
        action = _make_action(ActionKind.FEED)
        frontier = FrontierState(
            sml_coherent=True,
            runnable_items=[],
            selected_item=None,
            scheduler_context=_scheduler_block(RUNNABLE_PRIMARY),
        )
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.WAIT
        assert result.chainable is False
        assert "scheduler" not in (result.context or {})
        suppressed = result.context["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "FEED"
        assert result.context["wait_reason"] == "process_suppressed_no_alternative"


class TestRunnableNoSchedulerBackwardCompat:
    """AC-8: assignable runnable + missing scheduler context."""

    def test_disabled_feed_runnable_no_scheduler_uses_first_runnable(self):
        # No scheduler_context → backward-compat non-scheduler shape:
        # selected_item is runnable_items[0], no scheduler block.
        action = _make_action(ActionKind.FEED)
        frontier = FrontierState(
            sml_coherent=True,
            runnable_items=[RUNNABLE_PRIMARY, RUNNABLE_SECONDARY],
            selected_item=None,
            scheduler_context=None,
        )
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.CHARGE
        assert result.context["selected_item"] == RUNNABLE_PRIMARY
        assert "scheduler" not in result.context
        # skipped_process is still populated.
        assert result.context["skipped_process"]["process_key"] == "FEED"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _dummy_offer():
    from yoke_core.domain.session_contract import SessionOffer

    return SessionOffer(
        session_id="charge-ctx-sess",
        executor="claude-code",
        provider="anthropic",
        model="claude-opus-4-7",
        workspace="/tmp/yoke",
    )
