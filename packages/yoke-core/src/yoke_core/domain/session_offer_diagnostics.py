"""Offer-path elimination diagnostics shared by CLI and HTTP adapters."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .scheduler_types import is_assignable_claim_state
from .work_processes import list_processes


def _value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _item_ref(item_id: Any, conn: Any = None) -> str:
    from .sessions_queries_base import display_claim_item_id

    return display_claim_item_id(str(item_id), conn) or str(item_id)


def _step_refs(steps: Iterable[Any], conn: Any = None) -> List[str]:
    return [_item_ref(getattr(step, "item_id", ""), conn) for step in steps]


def _step_path(step: Any) -> str:
    return _value(getattr(step, "next_step", ""))


def _filter_entry(
    name: str,
    before: int,
    eliminated: int,
    **details: Any,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "filter": name,
        "candidates_before": before,
        "eliminated": eliminated,
        "candidates_after": max(0, before - eliminated),
    }
    entry.update(details)
    return entry


def _wip_occupants(schedule: Any, conn: Any = None) -> List[str]:
    return [
        _item_ref(item_id, conn)
        for item_id in getattr(schedule, "wip_active_items", [])
    ]


def _summary(entry: Mapping[str, Any]) -> str:
    name = entry["filter"]
    eliminated = int(entry.get("eliminated", 0))
    before = int(entry.get("candidates_before", 0))
    after = int(entry.get("candidates_after", 0))
    if name == "lane_compatibility":
        lane = entry.get("actual_lane") or "unknown"
        allowed = entry.get("allowed_paths")
        paths = "unrestricted" if allowed is None else ",".join(allowed) or "none"
        key = entry.get("config_key", "lane policy")
        return (
            f"lane compatibility ({lane}; {key}={paths}) eliminated "
            f"{eliminated} of {before} candidates ({after} remain)"
        )
    if name == "wip_cap":
        occupants = ",".join(entry.get("occupying_items", [])) or "none"
        return (
            f"WIP cap (wip_cap={entry.get('cap')}, active={entry.get('active')}; "
            f"occupying={occupants}) eliminated {eliminated} of {before} "
            f"candidates ({after} remain)"
        )
    if name == "claim_state":
        live = entry.get("claim_state_counts", {}).get("claimed_by_other_live", 0)
        return (
            f"claim state (claimed_by_other_live={live}) eliminated "
            f"{eliminated} of {before} candidates ({after} remain)"
        )
    if name == "posture_gate_holds":
        return (
            f"posture/gate holds (blocked={entry.get('blocked', 0)}, "
            f"exceptional={entry.get('exceptional', 0)}, "
            f"frozen={entry.get('frozen', 0)}) account for {eliminated} "
            f"of {before} frontier entries"
        )
    if name == "process_offers":
        disabled = [
            f"{offer['process_key']}:{offer['config_key']}"
            for offer in entry.get("offers", [])
            if offer.get("enabled") is False
        ]
        detail = ",".join(disabled) or "none disabled"
        return (
            f"process_offers ({detail}) eliminated {eliminated} of {before} "
            f"process candidates ({after} remain)"
        )
    return (
        f"{name} eliminated {eliminated} of {before} candidates "
        f"({after} remain)"
    )


def _with_top_eliminator(diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    chain = diagnostics.get("elimination_chain", [])
    top = max(
        chain,
        key=lambda entry: int(entry.get("eliminated", 0)),
        default=None,
    )
    if top is None:
        top = _filter_entry("none", 0, 0)
    top = dict(top)
    top["summary"] = _summary(top)
    diagnostics["top_eliminator"] = top
    diagnostics["summary"] = top["summary"]
    return diagnostics


def build_schedule_offer_diagnostics(
    *,
    candidate_steps: Sequence[Any],
    compatible_steps: Sequence[Any],
    lane_filtered_steps: Sequence[Any],
    wip_filtered_steps: Sequence[Any],
    claim_filtered_steps: Sequence[Any],
    schedule: Any,
    execution_lane: str,
    lane_allowed_paths: Optional[Mapping[str, Sequence[str]]],
    conn: Any = None,
) -> Dict[str, Any]:
    """Build the numbered static-filter chain for one session offer."""
    candidate_total = len(candidate_steps)
    lane_key = str(execution_lane or "").upper()
    allowed_paths = None
    if lane_allowed_paths and lane_key in lane_allowed_paths:
        allowed_paths = list(lane_allowed_paths[lane_key])

    claim_counts = Counter(
        _value(getattr(step, "claim_state", "unknown"))
        for step in claim_filtered_steps
    )
    blocked = list(getattr(schedule, "blocked_steps", []) or [])
    exceptional = list(getattr(schedule, "exceptional_steps", []) or [])
    frozen = list(getattr(schedule, "frozen_steps", []) or [])
    posture_holds = blocked + exceptional + frozen

    diagnostics: Dict[str, Any] = {
        "candidate_total": candidate_total,
        "candidate_paths": Counter(_step_path(step) for step in candidate_steps),
        "elimination_chain": [
            _filter_entry(
                "lane_compatibility",
                candidate_total,
                len(lane_filtered_steps),
                actual_lane=execution_lane,
                allowed_paths=allowed_paths,
                config_key=f"lane_paths_{str(execution_lane or 'unknown').lower()}",
                eliminated_items=_step_refs(lane_filtered_steps, conn),
            ),
            _filter_entry(
                "wip_cap",
                len(compatible_steps),
                len(wip_filtered_steps),
                cap=getattr(schedule, "wip_cap", None),
                active=getattr(schedule, "wip_active", 0),
                occupying_items=_wip_occupants(schedule, conn),
                eliminated_items=_step_refs(wip_filtered_steps, conn),
            ),
            _filter_entry(
                "claim_state",
                len(compatible_steps) - len(wip_filtered_steps),
                len(claim_filtered_steps),
                claim_state_counts=dict(sorted(claim_counts.items())),
                eliminated_items=_step_refs(claim_filtered_steps, conn),
            ),
            _filter_entry(
                "posture_gate_holds",
                candidate_total + len(posture_holds),
                len(posture_holds),
                blocked=len(blocked),
                exceptional=len(exceptional),
                frozen=len(frozen),
                held_items=_step_refs(posture_holds, conn),
            ),
        ],
        "remaining_candidates": sum(
            1
            for step in compatible_steps
            if step not in wip_filtered_steps
            and is_assignable_claim_state(getattr(step, "claim_state", None))
        ),
    }
    diagnostics["candidate_paths"] = dict(sorted(diagnostics["candidate_paths"].items()))
    for entry in diagnostics["elimination_chain"]:
        entry["summary"] = _summary(entry)
    return _with_top_eliminator(diagnostics)


def add_process_offer_diagnostics(
    diagnostics: Optional[Mapping[str, Any]],
    policy: Any,
) -> Dict[str, Any]:
    """Append process-offer flag state and source to the filter chain."""
    result = deepcopy(dict(diagnostics or {
        "candidate_total": 0,
        "elimination_chain": [],
        "remaining_candidates": 0,
    }))
    offers: List[Dict[str, Any]] = []
    for process_key in list_processes():
        if policy is None:
            enabled = None
            config_key = None
            config_source = "unresolved"
        else:
            enabled, config_key, config_source = policy.decision_for(process_key)
        offers.append({
            "process_key": process_key,
            "enabled": enabled,
            "config_key": config_key,
            "config_source": config_source,
        })
    result["elimination_chain"] = [
        entry
        for entry in result.get("elimination_chain", [])
        if entry.get("filter") != "process_offers"
    ]
    disabled = sum(offer.get("enabled") is False for offer in offers)
    process_entry = _filter_entry(
        "process_offers",
        len(offers),
        disabled,
        offers=offers,
    )
    process_entry["summary"] = _summary(process_entry)
    result["elimination_chain"].append(process_entry)
    return _with_top_eliminator(result)


def attach_offer_diagnostics(
    action: Any,
    diagnostics: Optional[Mapping[str, Any]],
    *,
    process_offer_policy: Any = None,
    actual_lane: Optional[str] = None,
) -> Any:
    """Attach diagnostics to a ``NextAction`` and enrich WAIT wording."""
    if diagnostics is None:
        diagnostics = {
            "candidate_total": 0,
            "elimination_chain": [],
            "remaining_candidates": 0,
        }
    enriched = add_process_offer_diagnostics(diagnostics, process_offer_policy)
    if actual_lane and not enriched.get("actual_lane"):
        enriched["actual_lane"] = actual_lane
    context = dict(action.context or {})
    context["offer_diagnostics"] = enriched
    updates: Dict[str, Any] = {"context": context}
    if _value(action.action) == "wait":
        top = enriched.get("top_eliminator") or {}
        if int(top.get("eliminated", 0)) > 0:
            updates["reason"] = (
                f"{str(action.reason).rstrip('.')} Top eliminator: "
                f"{top.get('summary', 'candidate filter applied')}."
            )
    return action.model_copy(update=updates)


__all__ = [
    "add_process_offer_diagnostics",
    "attach_offer_diagnostics",
    "build_schedule_offer_diagnostics",
]
