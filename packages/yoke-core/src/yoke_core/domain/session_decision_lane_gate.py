"""Shared lane-policy gate evaluator for session-offer decisions.

One helper, three call sites: ``decide_charge_action``,
``decide_resume_action``, and the process-offer gate's
``_evaluate_lane_gate`` all consult this evaluator. Centralizing the
decision closes the seam where an unknown lane silently bypassed
``lane_allowed_paths`` by returning ``None`` from
``lane_allowed_paths.get(lane_key)`` and falling through every
``configured_lane_paths is not None`` short-circuit.

The evaluator is a pure function over ``(execution_lane,
required_path, lane_allowed_paths)`` and returns one of three
verdicts:

- ``ALLOWED`` — the policy permits the path for this lane.
- ``WAIT_DISALLOWED`` — the lane has an explicit allowlist that
  excludes the required path. Operator can switch lanes or widen the
  allowlist.
- ``WAIT_UNKNOWN`` — the lane is missing from ``lane_allowed_paths``
  entirely (including the historical ``"primary"`` sentinel when no
  ``lane_paths_primary`` is configured). Operator must declare the
  lane in config before traffic on it can be routed; silently allowing
  every path was the regression.

Call sites build the corresponding ``NextAction`` (or a structurally
equivalent gate verdict) from the evaluator's verdict; this module
deliberately does NOT construct ``NextAction`` objects so it can be
consumed by both decision-engine code and downstream telemetry
without dragging the lane-policy-NextAction shape into helpers that
don't need it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from yoke_core.api.routing_config import normalize_token


class LaneGateVerdict(str, Enum):
    """Three-valued lane-policy verdict surfaced by :func:`evaluate_lane_gate`."""

    ALLOWED = "allowed"
    WAIT_DISALLOWED = "lane_policy_disallows_path"
    WAIT_UNKNOWN = "lane_policy_unknown"


@dataclass(frozen=True)
class LaneGateResult:
    """Verdict + context payload for :func:`evaluate_lane_gate` callers."""

    verdict: LaneGateVerdict
    lane_key: str
    required_path: Optional[str]
    allowed_paths: Optional[List[str]]
    configured_lanes: List[str]

    @property
    def is_blocked(self) -> bool:
        return self.verdict in (
            LaneGateVerdict.WAIT_DISALLOWED,
            LaneGateVerdict.WAIT_UNKNOWN,
        )

    def wait_context(self) -> Dict[str, object]:
        """Return the ``context`` dict for a WAIT ``NextAction`` from this verdict.

        Always carries ``wait_reason``, ``required_path``, and the lane
        identifier. ``WAIT_DISALLOWED`` also includes the configured
        ``allowed_paths`` for this lane; ``WAIT_UNKNOWN`` includes
        ``configured_lanes`` so the operator can see which lanes ARE
        declared and fix either the config or the caller.
        """
        ctx: Dict[str, object] = {
            "wait_reason": self.verdict.value,
            "required_path": self.required_path,
        }
        if self.verdict is LaneGateVerdict.WAIT_DISALLOWED:
            ctx["allowed_paths"] = list(self.allowed_paths or [])
        elif self.verdict is LaneGateVerdict.WAIT_UNKNOWN:
            ctx["unknown_lane"] = self.lane_key
            ctx["configured_lanes"] = sorted(self.configured_lanes)
        return ctx


def evaluate_lane_gate(
    *,
    execution_lane: Optional[str],
    required_path: Optional[str],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
) -> LaneGateResult:
    """Evaluate the lane-policy gate for an offered required path.

    Returns ``ALLOWED`` only when:

    - ``lane_allowed_paths`` is ``None`` or empty (no policy declared
      anywhere — fail-open is the explicit operator-default), OR
    - the lane key exists in ``lane_allowed_paths`` AND
      ``required_path`` is in the lane's configured allowlist.

    Returns ``WAIT_UNKNOWN`` when ``lane_allowed_paths`` declares at
    least one lane but the offering lane is not one of them. This is
    the regression fix: the previous code returned ``None``
    from ``lane_allowed_paths.get(lane)`` and then short-circuited the
    block, effectively turning every unknown lane into an "allow all"
    sentinel.

    Returns ``WAIT_DISALLOWED`` when the lane is declared but does not
    list ``required_path`` in its allowlist.

    ``required_path`` of ``None`` always resolves to ``ALLOWED`` — the
    caller is responsible for handling no-path situations (e.g.
    process actions without a registered path token) at the call site,
    not via this evaluator. The helper has nothing to gate without a
    path to compare against.
    """
    lane_key = normalize_token(execution_lane or "").upper()
    configured_lanes = sorted((lane_allowed_paths or {}).keys())

    if not lane_allowed_paths:
        # No policy declared at all — preserve backward-compatible
        # fail-open. Operators opt in by adding any ``lane_paths_*``
        # key to machine config.
        return LaneGateResult(
            verdict=LaneGateVerdict.ALLOWED,
            lane_key=lane_key,
            required_path=required_path,
            allowed_paths=None,
            configured_lanes=configured_lanes,
        )

    if required_path is None:
        # No path to gate against — nothing for the policy to refuse.
        return LaneGateResult(
            verdict=LaneGateVerdict.ALLOWED,
            lane_key=lane_key,
            required_path=None,
            allowed_paths=None,
            configured_lanes=configured_lanes,
        )

    configured = lane_allowed_paths.get(lane_key)
    if configured is None:
        return LaneGateResult(
            verdict=LaneGateVerdict.WAIT_UNKNOWN,
            lane_key=lane_key,
            required_path=required_path,
            allowed_paths=None,
            configured_lanes=configured_lanes,
        )

    if required_path not in configured:
        return LaneGateResult(
            verdict=LaneGateVerdict.WAIT_DISALLOWED,
            lane_key=lane_key,
            required_path=required_path,
            allowed_paths=list(configured),
            configured_lanes=configured_lanes,
        )

    return LaneGateResult(
        verdict=LaneGateVerdict.ALLOWED,
        lane_key=lane_key,
        required_path=required_path,
        allowed_paths=list(configured),
        configured_lanes=configured_lanes,
    )


__all__ = [
    "LaneGateResult",
    "LaneGateVerdict",
    "evaluate_lane_gate",
]
