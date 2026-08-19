"""Offer-path elimination diagnostics shared by CLI and HTTP adapters."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from yoke_contracts.project_contract.project_keys import (
    SESSION_ROUTING_CAPABILITY,
)

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
    }
    entry.update(details)
    return entry


def _wip_occupants(schedule: Any, conn: Any = None) -> List[str]:
    return [
        _item_ref(item_id, conn)
        for item_id in getattr(schedule, "wip_active_items", [])
    ]


def _top_entry(
    chain: Sequence[Mapping[str, Any]]
) -> Optional[Mapping[str, Any]]:
    """Return the chain entry that removed the most candidates."""
    return max(
        chain,
        key=lambda entry: int(entry.get("eliminated", 0)),
        default=None,
    )


#: Dropped from every projected entry: counts that are arithmetic on
#: ``candidates_before`` and the entry's own eliminated-items list.
_DERIVED_ENTRY_FIELDS = ("eliminated", "candidates_after")


def _projected_entry(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Return one chain entry without the fields beside it already imply.

    A filter that removed nothing collapses to its name and the count it was
    handed: its configuration describes an exclusion that did not happen.
    """
    if not int(entry.get("eliminated", 0)):
        return {
            "filter": entry["filter"],
            "candidates_before": entry.get("candidates_before", 0),
        }
    return {
        key: value
        for key, value in entry.items()
        if key not in _DERIVED_ENTRY_FIELDS
    }


def project_offer_diagnostics(
    diagnostics: Mapping[str, Any], *, work_selected: bool
) -> Dict[str, Any]:
    """Shape diagnostics by outcome: the decision, or why there is none.

    When the offer selected work, the decision is the answer and the chain is
    weight — one line names how many candidates there were, how many survived,
    and which filter removed the most. When nothing was runnable the chain is
    the only thing that can tell a session why, so it ships in full with the
    config keys behind each exclusion. That is deliberately not behind a flag:
    the no-work case is exactly when nobody thinks to ask for it.
    """
    chain = list(diagnostics.get("elimination_chain") or [])
    top = _top_entry(chain) or {"filter": "none", "eliminated": 0}
    projected: Dict[str, Any] = {
        "candidate_total": diagnostics.get("candidate_total", 0),
        "remaining_candidates": diagnostics.get("remaining_candidates", 0),
        "top_eliminator": {
            "filter": top["filter"],
            "eliminated": int(top.get("eliminated", 0)),
        },
    }
    if work_selected:
        return projected
    projected["elimination_chain"] = [_projected_entry(e) for e in chain]
    for key in ("candidate_paths", "actual_lane"):
        if diagnostics.get(key):
            projected[key] = diagnostics[key]
    return projected


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
                config_key=f"lane_paths.{lane_key or 'UNKNOWN'}",
                config_source=(
                    f"project capability {SESSION_ROUTING_CAPABILITY}"
                ),
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
    return diagnostics


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
    result["elimination_chain"].append(process_entry)
    return result


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
    work_selected = bool(context.get("selected_item") or context.get("item_id"))
    context["offer_diagnostics"] = project_offer_diagnostics(
        enriched, work_selected=work_selected
    )
    updates: Dict[str, Any] = {"context": context}
    top = _top_entry(list(enriched.get("elimination_chain") or []))
    if _value(action.action) == "wait" and top and int(top.get("eliminated", 0)):
        # The shipped chain carries the config behind the exclusion; the reason
        # only has to point at which filter to read.
        updates["reason"] = (
            f"{str(action.reason).rstrip('.')} Top eliminator: "
            f"{top['filter']} removed {top['eliminated']} of "
            f"{top.get('candidates_before', 0)} candidates."
        )
    return action.model_copy(update=updates)


__all__ = [
    "add_process_offer_diagnostics",
    "attach_offer_diagnostics",
    "build_schedule_offer_diagnostics",
    "project_offer_diagnostics",
]
