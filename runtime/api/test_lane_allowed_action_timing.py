"""When a routing edit reaches a session that is already running.

The two halves of routing take effect at different moments, and an operator
editing settings needs to know which they are changing:

* A lane is **stamped once**, at registration. Rewriting a live session's
  lane would move work away from a session already executing on it, so a
  routing edit reaches only sessions that register after it.
* A lane's **allowed actions** are read fresh on every session offer, so an
  allowlist edit reaches an already-registered session at its next offer,
  with no re-registration and no restart.

These are asserted through the gate the scheduler actually consults, so the
documented answer and the executed one cannot drift.
"""

from __future__ import annotations

from yoke_core.api.routing_config import load_routing_config
from yoke_core.domain.session_decision_lane_gate import (
    LaneGateVerdict,
    evaluate_lane_gate,
)

_BEFORE = {
    "executor_default_lanes": {"claude*": "DARIUS"},
    "lane_metadata": {"DARIUS": {"label": "DARIUS"}},
    "lane_paths": {"DARIUS": ["dash"]},
}
_AFTER = {
    **_BEFORE,
    "lane_paths": {"DARIUS": ["dash", "polish"]},
}


def _verdict(settings, path):
    config = load_routing_config("", project_settings=settings)
    return evaluate_lane_gate(
        execution_lane="DARIUS",
        required_path=path,
        lane_allowed_paths=config.lane_allowed_paths,
    ).verdict


class TestAllowedActionsTakeEffectAtTheNextOffer:
    def test_a_widened_allowlist_admits_the_new_action(self):
        assert _verdict(_BEFORE, "polish") is LaneGateVerdict.WAIT_DISALLOWED
        assert _verdict(_AFTER, "polish") is LaneGateVerdict.ALLOWED

    def test_a_narrowed_allowlist_refuses_the_removed_action(self):
        assert _verdict(_AFTER, "polish") is LaneGateVerdict.ALLOWED
        assert _verdict(
            {**_AFTER, "lane_paths": {"DARIUS": ["dash"]}}, "polish"
        ) is LaneGateVerdict.WAIT_DISALLOWED

    def test_the_gate_reads_the_settings_it_is_handed_every_time(self):
        # No cached policy sits between the capability and the gate, which
        # is why the answer changes without the session re-registering.
        assert _verdict(_BEFORE, "dash") is LaneGateVerdict.ALLOWED
        assert _verdict(_AFTER, "dash") is LaneGateVerdict.ALLOWED


class TestAnUnresolvedLaneCannotBecomeRunnable:
    def test_the_sentinel_lane_is_unknown_to_the_gate(self):
        config = load_routing_config("", project_settings=_AFTER)
        verdict = evaluate_lane_gate(
            execution_lane="primary",
            required_path="dash",
            lane_allowed_paths=config.lane_allowed_paths,
        ).verdict
        assert verdict is LaneGateVerdict.WAIT_UNKNOWN

    def test_a_lane_declared_only_by_a_rule_is_still_unknown_to_the_gate(self):
        # A rule can route a session onto a lane; only an allowlist makes
        # that lane runnable. Nothing about adding a rule silently opens one.
        settings = {
            **_AFTER,
            "lane_metadata": {**_AFTER["lane_metadata"], "MUSKY": {"label": "MUSKY"}},
            "lane_rules": [{"harness": "cursor", "lane": "MUSKY"}],
        }
        config = load_routing_config("", project_settings=settings)
        assert config.lane_for_session(executor="cursor-cli") == "MUSKY"
        assert evaluate_lane_gate(
            execution_lane="MUSKY",
            required_path="dash",
            lane_allowed_paths=config.lane_allowed_paths,
        ).verdict is LaneGateVerdict.WAIT_UNKNOWN
