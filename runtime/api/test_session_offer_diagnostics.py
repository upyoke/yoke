"""Offer-path diagnostics for lane, WIP, and process-policy eliminations."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.api.routing_config import ProcessOfferPolicy
from yoke_core.domain.scheduler_types import ClaimState, NextStep
from yoke_core.domain.session import ActionKind, FrontierState, decide_next_action
from yoke_core.domain.session_contract import NextAction
from yoke_core.domain.session_offer_diagnostics import (
    attach_offer_diagnostics,
    build_schedule_offer_diagnostics,
)
from runtime.api.session_start_test_helpers import make_offer as _make_offer


def _schedule(*, wip_cap: int, wip_active: int, wip_active_items: list[int]):
    return SimpleNamespace(
        blocked_steps=[],
        exceptional_steps=[],
        frozen_steps=[],
        wip_cap=wip_cap,
        wip_active=wip_active,
        wip_active_items=wip_active_items,
    )


def test_lane_excluded_dash_candidates_name_paths_and_count():
    """A lane-filtered DASH frontier explains the configured exclusion."""
    candidates = [
        SimpleNamespace(
            item_id=item_id,
            next_step=NextStep.DASH,
            claim_state=ClaimState.UNCLAIMED,
        )
        for item_id in range(1, 14)
    ]
    lane_paths = {"ALTMAN": ["refine", "polish"]}
    diagnostics = build_schedule_offer_diagnostics(
        candidate_steps=candidates,
        compatible_steps=[],
        lane_filtered_steps=candidates,
        wip_filtered_steps=[],
        claim_filtered_steps=[],
        schedule=_schedule(wip_cap=5, wip_active=0, wip_active_items=[]),
        execution_lane="ALTMAN",
        lane_allowed_paths=lane_paths,
    )
    frontier = FrontierState(
        runnable_items=[],
        sml_coherent=True,
        lane_filtered_count=len(candidates),
        offer_diagnostics=diagnostics,
    )

    result = decide_next_action(
        _make_offer(execution_lane="ALTMAN"),
        frontier,
        process_offer_policy=ProcessOfferPolicy(default_enabled=True),
        lane_allowed_paths=lane_paths,
    )

    assert result.action == ActionKind.WAIT
    offer_diagnostics = result.context["offer_diagnostics"]
    lane_entry = next(
        entry
        for entry in offer_diagnostics["elimination_chain"]
        if entry["filter"] == "lane_compatibility"
    )
    # The count is the length of the list beside it, never a second field.
    assert len(lane_entry["eliminated_items"]) == 13
    assert "eliminated" not in lane_entry
    assert "candidates_after" not in lane_entry
    assert "summary" not in lane_entry
    assert lane_entry["allowed_paths"] == ["refine", "polish"]
    assert lane_entry["config_key"] == "lane_paths.ALTMAN"
    assert lane_entry["config_source"] == "project capability session-routing"
    assert offer_diagnostics["top_eliminator"] == {
        "filter": "lane_compatibility",
        "eliminated": 13,
    }
    assert "lane_compatibility removed 13 of 13" in result.reason


def test_wip_saturated_candidates_name_cap_active_count_and_occupants():
    """A WIP-filtered WAIT identifies the cap, count, and occupying items."""
    candidates = [
        SimpleNamespace(
            item_id=item_id,
            next_step=NextStep.CONDUCT,
            claim_state=ClaimState.UNCLAIMED,
        )
        for item_id in (41, 42, 43)
    ]
    diagnostics = build_schedule_offer_diagnostics(
        candidate_steps=candidates,
        compatible_steps=candidates,
        lane_filtered_steps=[],
        wip_filtered_steps=candidates,
        claim_filtered_steps=[],
        schedule=_schedule(wip_cap=2, wip_active=2, wip_active_items=[901, 902]),
        execution_lane="DARIUS",
        lane_allowed_paths={"DARIUS": ["conduct"]},
    )
    frontier = FrontierState(
        runnable_items=[],
        sml_coherent=True,
        offer_diagnostics=diagnostics,
    )
    policy = ProcessOfferPolicy(
        default_enabled=False,
        shared_project_default=False,
        shared_project_source="project capability session-routing",
    )

    result = decide_next_action(
        _make_offer(execution_lane="DARIUS"),
        frontier,
        process_offer_policy=policy,
    )

    assert result.action == ActionKind.WAIT
    offer_diagnostics = result.context["offer_diagnostics"]
    wip_entry = next(
        entry
        for entry in offer_diagnostics["elimination_chain"]
        if entry["filter"] == "wip_cap"
    )
    assert wip_entry["cap"] == 2
    assert wip_entry["active"] == 2
    assert wip_entry["occupying_items"] == ["901", "902"]
    assert len(wip_entry["eliminated_items"]) == 3
    assert offer_diagnostics["top_eliminator"] == {
        "filter": "wip_cap",
        "eliminated": 3,
    }
    assert "wip_cap removed 3 of 3" in result.reason
    process_entry = next(
        entry
        for entry in offer_diagnostics["elimination_chain"]
        if entry["filter"] == "process_offers"
    )
    assert all(
        offer["config_source"] == "project capability session-routing"
        for offer in process_entry["offers"]
    )


def _dash_candidates(
    count: int, *, claimed: int = 0
) -> list[SimpleNamespace]:
    """Return DASH candidates whose first *claimed* entries are held live."""
    return [
        SimpleNamespace(
            item_id=item_id,
            next_step=NextStep.DASH,
            claim_state=(
                ClaimState.CLAIMED_BY_OTHER_LIVE
                if item_id <= claimed
                else ClaimState.UNCLAIMED
            ),
        )
        for item_id in range(1, count + 1)
    ]


def _selected_action(diagnostics) -> object:
    return attach_offer_diagnostics(
        NextAction(
            action=ActionKind.CHARGE,
            reason="1 runnable item(s) on the frontier; selected YOK-9.",
            chainable=True,
            correlation_id="session-1",
            context={"selected_item": "YOK-9", "runnable_items": ["YOK-9"]},
        ),
        diagnostics,
        process_offer_policy=ProcessOfferPolicy(default_enabled=True),
    )


def test_selected_work_ships_the_decision_not_the_chain():
    """The decision is the answer; the chain is weight the session cannot use."""
    candidates = _dash_candidates(20, claimed=15)
    claimed = candidates[:15]
    diagnostics = build_schedule_offer_diagnostics(
        candidate_steps=candidates,
        compatible_steps=candidates,
        lane_filtered_steps=[],
        wip_filtered_steps=[],
        claim_filtered_steps=claimed,
        schedule=_schedule(wip_cap=30, wip_active=0, wip_active_items=[]),
        execution_lane="DARIUS",
        lane_allowed_paths={"DARIUS": ["dash"]},
    )

    shipped = _selected_action(diagnostics).context["offer_diagnostics"]

    assert shipped == {
        "candidate_total": 20,
        "remaining_candidates": 5,
        "top_eliminator": {"filter": "claim_state", "eliminated": 15},
    }


def test_no_runnable_work_ships_the_chain_that_explains_it():
    """The chain is the only thing that can answer "why is there none for me"."""
    candidates = _dash_candidates(13)
    diagnostics = build_schedule_offer_diagnostics(
        candidate_steps=candidates,
        compatible_steps=[],
        lane_filtered_steps=candidates,
        wip_filtered_steps=[],
        claim_filtered_steps=[],
        schedule=_schedule(wip_cap=5, wip_active=0, wip_active_items=[]),
        execution_lane="ALTMAN",
        lane_allowed_paths={"ALTMAN": ["refine", "polish"]},
    )

    shipped = attach_offer_diagnostics(
        NextAction(
            action=ActionKind.WAIT,
            reason="No actionable work.",
            chainable=False,
            correlation_id="session-1",
            context={},
        ),
        diagnostics,
        process_offer_policy=ProcessOfferPolicy(default_enabled=True),
        actual_lane="ALTMAN",
    ).context["offer_diagnostics"]

    lane_entry = next(
        entry
        for entry in shipped["elimination_chain"]
        if entry["filter"] == "lane_compatibility"
    )
    assert lane_entry["config_key"] == "lane_paths.ALTMAN"
    assert lane_entry["config_source"] == "project capability session-routing"
    assert shipped["actual_lane"] == "ALTMAN"
    assert shipped["candidate_paths"] == {"dash": 13}


def test_a_filter_that_removed_nothing_collapses_to_its_name():
    """Config behind an exclusion that did not happen explains nothing."""
    candidates = _dash_candidates(4, claimed=4)
    diagnostics = build_schedule_offer_diagnostics(
        candidate_steps=candidates,
        compatible_steps=candidates,
        lane_filtered_steps=[],
        wip_filtered_steps=[],
        claim_filtered_steps=candidates,
        schedule=_schedule(wip_cap=30, wip_active=0, wip_active_items=[]),
        execution_lane="DARIUS",
        lane_allowed_paths={"DARIUS": ["dash"]},
    )

    shipped = attach_offer_diagnostics(
        NextAction(
            action=ActionKind.WAIT,
            reason="No actionable work.",
            chainable=False,
            correlation_id="session-1",
            context={},
        ),
        diagnostics,
        process_offer_policy=ProcessOfferPolicy(default_enabled=True),
    ).context["offer_diagnostics"]

    collapsed = next(
        entry
        for entry in shipped["elimination_chain"]
        if entry["filter"] == "lane_compatibility"
    )
    assert collapsed == {"filter": "lane_compatibility", "candidates_before": 4}
