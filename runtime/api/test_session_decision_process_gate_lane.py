"""Lane-allowlist gate regressions for process actions.

Covers:

* AC-1 - lane disallows ``feed`` -> WAIT, not FEED.
* AC-2 - lane disallows ``strategize`` -> WAIT, not STRATEGIZE.
* AC-3 - global process policy wins when both gates would block.
* AC-4 - backward-compat: no lane policy preserves legacy behavior.
* AC-5 - lane opt-in: process action passes through.
* AC-9 - machine config supports the process/lane policy tokens.
* AC-10 - ``ActionKind`` has no ``DOCTOR`` member.
* AC-11 - lane WAIT does not record disabled-process skip memory.

Path-vocab unit tests for :func:`process_key_to_path` round out the
sibling module so the map cannot regress silently.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from yoke_core.domain.session_contract import (
    ActionKind,
    FrontierState,
    NextAction,
    SessionOffer,
)
from yoke_core.domain.session_decision import decide_next_action
from yoke_core.domain.session_decision_process_gate import (
    _extract_skip_context,
    apply_process_offer_gate,
)
from yoke_core.domain.work_processes import (
    PROCESS_DOCTOR,
    PROCESS_FEED,
    PROCESS_STRATEGIZE,
    process_key_to_path,
)
from yoke_core.api.routing_config import ProcessOfferPolicy
from yoke_core.api.routing_config import load_process_offer_policy, load_routing_config


def _make_offer(**overrides) -> SessionOffer:
    defaults = {
        "session_id": "lane-sess",
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
        correlation_id=kwargs.pop("correlation_id", "lane-sess"),
        context=kwargs.pop("context", {}),
    )


def _drift_frontier(*, runnable_items=None, sml_coherent=True) -> FrontierState:
    return FrontierState(
        sml_coherent=sml_coherent,
        runnable_items=runnable_items or [],
        scheduler_context={} if runnable_items else None,
        drift_review={
            "classification": "sml_only",
            "summary": "lane-gate test",
            "checkpoint_start": "",
            "reviewed_through": "",
            "delivered_items": [],
        },
    )


class TestProcessKeyToPath:
    """Sibling map covers every registered process key."""

    def test_strategize_path(self):
        assert process_key_to_path(PROCESS_STRATEGIZE) == "strategize"

    def test_feed_path(self):
        assert process_key_to_path(PROCESS_FEED) == "feed"

    def test_doctor_path(self):
        # Doctor is recognized as vocabulary even though
        # decide_next_action does not emit a DOCTOR action.
        assert process_key_to_path(PROCESS_DOCTOR) == "doctor"

    def test_unknown_returns_none(self):
        assert process_key_to_path("UNKNOWN") is None

    def test_empty_returns_none(self):
        assert process_key_to_path("") is None

    def test_lower_case_normalized(self):
        assert process_key_to_path("feed") == "feed"


class TestActionKindDoesNotIncludeDoctor:
    """AC-10: ActionKind has no DOCTOR member."""

    def test_no_doctor_action_kind(self):
        kinds = {kind.value for kind in ActionKind}
        assert "doctor" not in kinds


class TestLaneGateBlocksFeed:
    """AC-1 / AC-3: lane allowlist excludes ``feed`` -> WAIT."""

    def test_feed_lane_block_returns_wait(self):
        action = _make_action(
            ActionKind.FEED,
            reason="No runnable items but strategy is coherent; materialize more work.",
            context={"blocked_count": 0, "trigger": "no_runnable_items"},
        )
        result = apply_process_offer_gate(
            action,
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"feed": True}),
            lane_allowed_paths={"ALTMAN": ["refine", "polish"]},
            execution_lane="ALTMAN",
        )
        assert result.action == ActionKind.WAIT
        assert result.chainable is False
        ctx = result.context
        assert ctx["wait_reason"] == "lane_policy_disallows_path"
        assert ctx["actual_lane"] == "ALTMAN"
        assert ctx["required_path"] == "feed"
        assert ctx["allowed_paths"] == ["refine", "polish"]
        assert ctx["recommended_action"] == "feed"
        assert ctx["process_key"] == "FEED"
        # Lane WAIT must NOT carry skipped_process / disabled-process
        # markers; that signal is reserved for do_process_offer_*=false.
        assert "skipped_process" not in ctx
        assert "process_disabled" not in ctx
        assert "disabled_process_key" not in ctx
        assert "ALTMAN" in result.reason
        assert "feed" in result.reason

    def test_disabled_policy_overrides_feed_lane_block(self):
        # When FEED is globally disabled AND the lane allowlist excludes
        # feed, the policy gate wins. The response names the load-bearing
        # config key (``do_process_offer_feed``) rather than the lane:
        # switching lanes cannot unblock a globally-disabled process.
        # With no runnable items, the gate returns a suppressed-WAIT
        # carrying the process recommendation as informational context.
        result = apply_process_offer_gate(
            _make_action(ActionKind.FEED),
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(),  # FEED disabled
            lane_allowed_paths={"ALTMAN": ["refine", "polish"]},
            execution_lane="ALTMAN",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "process_suppressed_no_alternative"
        suppressed = result.context["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "FEED"
        assert suppressed["config_key"] == "do_process_offer_feed"
        # The lane WAIT shape's lane keys must NOT appear — the
        # suppressed-WAIT is a distinct shape from the lane WAIT.
        assert "actual_lane" not in result.context
        assert "allowed_paths" not in result.context
        # No CHARGE-swap skipped_process marker — that's the runnable path.
        assert "skipped_process" not in result.context


class TestLaneGateBlocksStrategize:
    """AC-2 / AC-3: lane allowlist excludes ``strategize`` -> WAIT."""

    def test_strategize_lane_block_returns_wait(self):
        result = apply_process_offer_gate(
            _make_action(
                ActionKind.STRATEGIZE,
                reason="Strategic layer needs attention: SML is absent or incoherent.",
                context={"sml_coherent": False},
            ),
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"strategize": True}),
            lane_allowed_paths={
                "DARIUS": ["shepherd", "advance", "conduct", "usher"],
            },
            execution_lane="DARIUS",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"
        assert result.context["actual_lane"] == "DARIUS"
        assert result.context["required_path"] == "strategize"
        assert result.context["recommended_action"] == "strategize"
        # original_context preserved for diagnostics.
        assert result.context["original_context"] == {"sml_coherent": False}

    def test_strategize_lane_block_via_decide_next_action(self):
        # End-to-end: sml_incoherent + lane that excludes strategize.
        result = decide_next_action(
            _make_offer(execution_lane="DARIUS"),
            FrontierState(sml_coherent=False, runnable_items=[]),
            lane_allowed_paths={
                "DARIUS": ["shepherd", "advance", "conduct", "usher"],
            },
            process_offer_policy=ProcessOfferPolicy(per_process={"strategize": True}),
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"
        assert result.context["required_path"] == "strategize"


class TestLaneAllowsProcessAction:
    """AC-5: lane explicitly opts in -> action passes through."""

    def test_lane_allows_feed_returns_feed(self):
        action = _make_action(ActionKind.FEED)
        result = apply_process_offer_gate(
            action,
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"feed": True}),
            lane_allowed_paths={"STRATEGY": ["feed", "strategize"]},
            execution_lane="STRATEGY",
        )
        assert result is action

    def test_lane_allows_strategize_via_decide_next_action(self):
        result = decide_next_action(
            _make_offer(execution_lane="STRATEGY"),
            FrontierState(sml_coherent=False, runnable_items=[]),
            lane_allowed_paths={"STRATEGY": ["feed", "strategize"]},
            process_offer_policy=ProcessOfferPolicy(per_process={"strategize": True}),
        )
        assert result.action == ActionKind.STRATEGIZE


class TestBackwardCompatNoLanePolicy:
    """AC-4: no lane policy -> existing policy-only behavior holds."""

    def test_feed_no_lane_policy_passes_through(self):
        action = _make_action(ActionKind.FEED)
        result = apply_process_offer_gate(
            action,
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"feed": True}),
            lane_allowed_paths=None,
            execution_lane="ALTMAN",
        )
        assert result is action

    def test_feed_empty_lane_policy_passes_through(self):
        action = _make_action(ActionKind.FEED)
        result = apply_process_offer_gate(
            action,
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"feed": True}),
            lane_allowed_paths={},
            execution_lane="ALTMAN",
        )
        assert result is action

    def test_unconfigured_lane_waits_with_lane_policy_unknown(self):
        # lane policy exists for another lane only; unconfigured
        # lane no longer fails open. Emits WAIT with lane_policy_unknown.
        action = _make_action(ActionKind.FEED)
        result = apply_process_offer_gate(
            action,
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"feed": True}),
            lane_allowed_paths={"DARIUS": ["shepherd", "advance"]},
            execution_lane="UNKNOWN_LANE",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"
        assert result.context["unknown_lane"] == "UNKNOWN_LANE"
        assert result.context["configured_lanes"] == ["DARIUS"]

    def test_no_lane_via_decide_next_action_returns_feed(self):
        # AC-4 reproduction: no lane policy + FEED enabled +
        # empty runnable + sml_coherent -> FEED unchanged.
        result = decide_next_action(
            _make_offer(),
            FrontierState(sml_coherent=True, runnable_items=[]),
            lane_allowed_paths=None,
            process_offer_policy=ProcessOfferPolicy(per_process={"feed": True}),
        )
        assert result.action == ActionKind.FEED


class TestNoSkipMemoryOnLaneBlock:
    """AC-11: lane block does not record disabled-process skip memory.

    The lane WAIT path is reserved for the case where the global
    policy *enables* the process but the lane allowlist excludes the
    path. Switching lanes could still unblock the action, so skip
    memory must not deduplicate on the process key.
    """

    def test_lane_wait_payload_has_no_skip_marker(self):
        result = apply_process_offer_gate(
            _make_action(ActionKind.FEED),
            _drift_frontier(runnable_items=[]),
            "corr",
            ProcessOfferPolicy(per_process={"feed": True}),  # FEED enabled
            lane_allowed_paths={"ALTMAN": ["refine"]},
            execution_lane="ALTMAN",
        )
        # With the policy enabled, the lane gate is the only filter and
        # the result is a WAIT carrying lane_policy_disallows_path,
        # never a disabled-process skip payload.
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"
        assert _extract_skip_context(result) is None


class TestMachineConfigSupportsProcessTokens:
    """AC-9: machine config accepts feed/strategize/doctor policy tokens."""

    def test_machine_config_json_process_tokens(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(
            "{\n"
            '  "settings": {\n'
            '    "do_process_offer_feed": true,\n'
            '    "do_process_offer_strategize": true,\n'
            '    "do_process_offer_doctor": false,\n'
            '    "lane_paths_strategy": "feed,strategize"\n'
            "  }\n"
            "}\n",
            encoding="utf-8",
        )

        policy = load_process_offer_policy(config_path)
        routing = load_routing_config(config_path)

        assert policy.is_enabled("FEED") is True
        assert policy.is_enabled("STRATEGIZE") is True
        assert policy.is_enabled("DOCTOR") is False
        assert routing.lane_allowed_paths["STRATEGY"] == ["feed", "strategize"]
