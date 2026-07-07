"""Process-offer policy gate regressions for ``decide_next_action``.

Covers AC-17 / AC-20 / AC-23 / AC-43 / AC-46. AC-20 (step-3 drift
Strategize disabled with runnable item available) and AC-46 share the
same swap-to-CHARGE shape and are covered by
``test_drift_strategize_with_disabled_policy_swaps_to_runnable``.
Skip-memory recording tests live in the sibling
``test_session_decision_process_skip_recording`` module so this file
stays under the 350-line cap.

* Process-backed actions (``STRATEGIZE``, ``FEED``) are filtered through
  the per-process policy before being returned.
* When the recommended process is disabled and runnable items exist on
  the frontier, the gate selects the first runnable item as a ``CHARGE``
  and records the skipped process under ``context['skipped_process']``.
* When the recommended process is disabled and no runnable items
  exist, the gate returns a non-chainable ``WAIT`` carrying
  ``context['wait_reason'] = 'process_suppressed_no_alternative'`` and
  a ``context['suppressed_process_recommendation']`` payload naming
  the direct command and the disabling config key. The disabled
  process never surfaces as a terminal ``ESCALATE``.
* When no policy is plumbed through, the original action is returned
  unchanged (legacy callers stay unbroken).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session_contract import (
    ActionKind,
    FrontierState,
    NextAction,
    SessionOffer,
)
from yoke_core.domain.session_decision import decide_next_action
from yoke_core.domain.session_decision_process_gate import (
    apply_process_offer_gate,
    is_process_action_disabled,
)
from yoke_core.api.routing_config import ProcessOfferPolicy


RUNNABLE_A_ID = 1605
RUNNABLE_B_ID = 1606
RUNNABLE_C_ID = 1700
RUNNABLE_A = f"YOK-{RUNNABLE_A_ID}"
RUNNABLE_B = f"YOK-{RUNNABLE_B_ID}"
RUNNABLE_C = f"YOK-{RUNNABLE_C_ID}"


def _make_offer(**overrides) -> SessionOffer:
    defaults = {
        "session_id": "gate-sess",
        "executor": "claude-code",
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "workspace": "/tmp/yoke",
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


def _make_action(kind: ActionKind, **kwargs) -> NextAction:
    return NextAction(
        action=kind,
        reason=kwargs.pop("reason", f"{kind.value} test"),
        chainable=kwargs.pop("chainable", False),
        correlation_id=kwargs.pop("correlation_id", "gate-sess"),
        context=kwargs.pop("context", {}),
    )


def _drift_frontier(
    *,
    classification: str = "sml_only",
    runnable_items: list | None = None,
    sml_coherent: bool = True,
) -> FrontierState:
    """Build a FrontierState that defers to drift_action.

    ``charge_action`` claims the offer first when ``frontier.selected_item``
    is set OR ``frontier.runnable_items`` is non-empty AND
    ``scheduler_context is None``. The gate tests need drift_action to
    fire while still surfacing ``runnable_items`` to the gate, so the
    fixture forces ``charge_action`` to return None by leaving
    ``selected_item=None`` and supplying a non-None ``scheduler_context``
    (the empty dict is sufficient because the charge fallback only fires
    when ``scheduler_context is None``).
    """
    return FrontierState(
        sml_coherent=sml_coherent,
        runnable_items=runnable_items or [],
        scheduler_context={} if runnable_items else None,
        drift_review={
            "classification": classification,
            "summary": "process-gate test",
            "checkpoint_start": "",
            "reviewed_through": "",
            "delivered_items": [],
        },
    )


class TestIsProcessActionDisabled:
    """Helper: is_process_action_disabled returns the disabled key or None."""

    def test_returns_none_when_policy_is_none(self):
        action = _make_action(ActionKind.STRATEGIZE)
        assert is_process_action_disabled(action, None) is None

    def test_returns_none_for_non_process_action(self):
        policy = ProcessOfferPolicy()  # all disabled
        for kind in (ActionKind.RESUME, ActionKind.CHARGE,
                     ActionKind.WAIT, ActionKind.ESCALATE):
            action = _make_action(kind)
            assert is_process_action_disabled(action, policy) is None

    def test_returns_process_key_for_disabled_strategize(self):
        policy = ProcessOfferPolicy()  # all disabled
        action = _make_action(ActionKind.STRATEGIZE)
        assert is_process_action_disabled(action, policy) == "STRATEGIZE"

    def test_returns_process_key_for_disabled_feed(self):
        policy = ProcessOfferPolicy()  # all disabled
        action = _make_action(ActionKind.FEED)
        assert is_process_action_disabled(action, policy) == "FEED"

    def test_returns_none_when_policy_enables_process(self):
        policy = ProcessOfferPolicy(per_process={"strategize": True})
        action = _make_action(ActionKind.STRATEGIZE)
        assert is_process_action_disabled(action, policy) is None


class TestApplyProcessOfferGateNoOp:
    """Gate is a no-op for non-process / no-policy / enabled cases."""

    def test_no_policy_returns_action_unchanged(self):
        action = _make_action(ActionKind.STRATEGIZE)
        frontier = _drift_frontier()
        result = apply_process_offer_gate(action, frontier, "corr", None)
        assert result is action

    def test_non_process_action_returns_unchanged(self):
        action = _make_action(ActionKind.CHARGE, chainable=True)
        frontier = _drift_frontier()
        policy = ProcessOfferPolicy()  # all disabled — should still be no-op
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result is action

    def test_enabled_process_returns_unchanged(self):
        action = _make_action(ActionKind.STRATEGIZE)
        frontier = _drift_frontier()
        policy = ProcessOfferPolicy(per_process={"strategize": True})
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result is action


class TestApplyProcessOfferGateSwapToCharge:
    """AC-43: disabled process + runnable items -> swap to CHARGE."""

    def test_disabled_strategize_with_runnable_items_returns_charge(self):
        action = _make_action(
            ActionKind.STRATEGIZE,
            reason="Drift review: SML impacted. summary",
        )
        frontier = _drift_frontier(runnable_items=[RUNNABLE_A, RUNNABLE_B])
        policy = ProcessOfferPolicy()  # default disabled
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.CHARGE
        assert result.chainable is True
        assert result.context["selected_item"] == RUNNABLE_A
        skipped = result.context["skipped_process"]
        assert skipped["process_key"] == "STRATEGIZE"
        assert skipped["config_key"] == "do_process_offer_strategize"
        assert skipped["recommended_action"] == "strategize"
        assert skipped["skip_reason"] == "process_disabled_by_config"
        assert skipped["direct_command"] == "/yoke strategize"

    def test_disabled_feed_with_runnable_items_returns_charge(self):
        action = _make_action(ActionKind.FEED)
        frontier = _drift_frontier(runnable_items=[RUNNABLE_C])
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.CHARGE
        assert result.chainable is True
        assert result.context["selected_item"] == RUNNABLE_C
        assert result.context["skipped_process"]["process_key"] == "FEED"


class TestApplyProcessOfferGateSuppressedWait:
    """Disabled process + no runnable items -> suppressed-WAIT (non-terminal)."""

    def test_disabled_strategize_without_runnable_returns_suppressed_wait(self):
        action = _make_action(
            ActionKind.STRATEGIZE,
            reason="Drift review: SML impacted. summary",
            context={"sml_coherent": True},
        )
        frontier = _drift_frontier(runnable_items=[])
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.WAIT
        assert result.chainable is False
        assert "STRATEGIZE" in result.reason
        assert "/yoke strategize" in result.reason
        assert "do_process_offer_strategize" in result.reason
        ctx = result.context
        assert ctx["wait_reason"] == "process_suppressed_no_alternative"
        suppressed = ctx["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "STRATEGIZE"
        assert suppressed["config_key"] == "do_process_offer_strategize"
        assert suppressed["recommended_action"] == "strategize"
        assert suppressed["direct_command"] == "/yoke strategize"
        assert suppressed["skip_reason"] == "process_disabled_by_config"
        assert suppressed["original_reason"] == "Drift review: SML impacted. summary"
        # original_context preserved verbatim so reviewers see what the
        # decision engine wanted to do, and the drift-checkpoint
        # predicate can read trigger='drift_review' through this path.
        assert suppressed["original_context"] == {"sml_coherent": True}

    def test_disabled_feed_without_runnable_returns_suppressed_wait(self):
        action = _make_action(ActionKind.FEED)
        frontier = _drift_frontier(runnable_items=[])
        policy = ProcessOfferPolicy()
        result = apply_process_offer_gate(action, frontier, "corr", policy)
        assert result.action == ActionKind.WAIT
        assert "FEED" in result.reason
        suppressed = result.context["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "FEED"
        assert suppressed["direct_command"] == "/yoke feed"


class TestDecideNextActionWiring:
    """AC-20 / AC-43 / AC-46: decide_next_action plumbs the policy through drift."""

    def test_drift_returns_strategize_without_policy_keeps_legacy_behavior(self):
        # Legacy callers without a policy still receive the raw
        # process action; the gate is opt-in via the keyword argument.
        frontier = _drift_frontier(runnable_items=[RUNNABLE_A])
        result = decide_next_action(_make_offer(), frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_drift_strategize_with_disabled_policy_swaps_to_runnable(self):
        # AC-20 / AC-46 reproduction: drift recommends Strategize first
        # (step-3 chain shape), the policy disables Strategize for
        # /yoke do, and a runnable item exists. The gate selects
        # that item as a CHARGE candidate rather than short-circuiting
        # frontier scheduling on Strategize.
        frontier = _drift_frontier(runnable_items=[RUNNABLE_A])
        policy = ProcessOfferPolicy()  # default disabled
        result = decide_next_action(
            _make_offer(),
            frontier,
            process_offer_policy=policy,
        )
        assert result.action == ActionKind.CHARGE
        assert result.context["selected_item"] == RUNNABLE_A
        assert result.context["skipped_process"]["process_key"] == "STRATEGIZE"

    def test_drift_strategize_with_disabled_policy_no_runnable_suppressed_wait(self):
        # When no other candidates exist, the gate returns a suppressed
        # WAIT rather than dispatching the disabled process. The WAIT
        # is non-chainable but non-terminal — the operator sees the
        # recommendation as informational context rather than as the
        # cause of a terminal escalate.
        frontier = _drift_frontier(runnable_items=[])
        policy = ProcessOfferPolicy()
        result = decide_next_action(
            _make_offer(),
            frontier,
            process_offer_policy=policy,
        )
        assert result.action == ActionKind.WAIT
        assert result.chainable is False
        ctx = result.context
        assert ctx["wait_reason"] == "process_suppressed_no_alternative"
        assert ctx["suppressed_process_recommendation"]["process_key"] == "STRATEGIZE"

    def test_drift_with_enabled_policy_passes_through(self):
        # Operators who explicitly authorize Strategize get the legacy
        # process action.
        frontier = _drift_frontier(runnable_items=[RUNNABLE_A])
        policy = ProcessOfferPolicy(per_process={"strategize": True})
        result = decide_next_action(
            _make_offer(),
            frontier,
            process_offer_policy=policy,
        )
        assert result.action == ActionKind.STRATEGIZE

    def test_no_runnable_no_drift_with_disabled_policy_suppressed_wait(self):
        # The "no runnable items but SML coherent -> FEED" branch is
        # also gated; with FEED disabled and no runnable, the engine
        # returns the suppressed WAIT.
        frontier = FrontierState(sml_coherent=True, runnable_items=[])
        policy = ProcessOfferPolicy()
        result = decide_next_action(
            _make_offer(),
            frontier,
            process_offer_policy=policy,
        )
        assert result.action == ActionKind.WAIT
        suppressed = result.context["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "FEED"

    def test_sml_incoherent_with_disabled_policy_suppressed_wait(self):
        # The "not sml_coherent -> STRATEGIZE" branch is also gated.
        frontier = FrontierState(sml_coherent=False, runnable_items=[])
        policy = ProcessOfferPolicy()
        result = decide_next_action(
            _make_offer(),
            frontier,
            process_offer_policy=policy,
        )
        assert result.action == ActionKind.WAIT
        assert (
            result.context["suppressed_process_recommendation"]["process_key"]
            == "STRATEGIZE"
        )


class TestDriftFrontierOnlyDisabledFeedNoRunnable:
    """Today-reproduction: FEED disabled + frontier_only drift + zero runnable."""

    def test_response_is_non_terminal_wait_never_escalate(self):
        # After a merge burst, drift fires with classification='frontier_only'
        # but zero runnable items survive. With do_process_offer_feed=false,
        # the suppressed-WAIT shape is non-terminal so /yoke do does not
        # stall, and original_context.trigger='drift_review' preserves the
        # drift cursor advance.
        frontier = _drift_frontier(classification="frontier_only", runnable_items=[])
        result = decide_next_action(
            _make_offer(), frontier, process_offer_policy=ProcessOfferPolicy(),
        )
        assert result.action == ActionKind.WAIT
        assert result.action != ActionKind.ESCALATE
        assert result.context["wait_reason"] == "process_suppressed_no_alternative"
        suppressed = result.context["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "FEED"
        assert suppressed["config_key"] == "do_process_offer_feed"
        assert suppressed["direct_command"] == "/yoke feed"
        assert suppressed["original_context"].get("trigger") == "drift_review"
