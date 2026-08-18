"""Workspace-home frontier filter and runnable-elsewhere WAIT."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.scheduler_types import ClaimState, NextStep, SchedulerResult
from yoke_core.domain.session import ActionKind, FrontierState, SessionOffer
from yoke_core.domain.session_decision import decide_next_action
from yoke_core.domain.session_workspace_frontier import (
    apply_workspace_home_filter,
    enrich_elsewhere_checkout_paths,
    render_runnable_elsewhere_note,
    resolve_offer_home_project,
    workspace_home_filter_requested,
)


def _step(item_id: int, project: str, *, assignable: bool = True):
    from yoke_core.domain.scheduler_types import ScheduledStep

    return ScheduledStep(
        item_id=item_id,
        workflow_id="dash",
        workflow_version_id=1,
        workflow_version=1,
        status="idea",
        title=f"item {item_id}",
        priority="medium",
        next_step=NextStep.DASH,
        project=project,
        claim_state=ClaimState.UNCLAIMED if assignable else ClaimState.CLAIMED_BY_OTHER_LIVE,
    )


def _offer() -> SessionOffer:
    return SessionOffer(
        session_id="sess-home",
        executor="cursor",
        provider="cursor",
        model="test",
        workspace="/tmp/unmapped-does-not-exist",
    )


def test_filter_keeps_home_and_stashes_elsewhere(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.session_workspace_frontier._home_slug",
        lambda _conn, pid: {1: "yoke", 2: "platform"}[int(pid)],
    )
    home = _step(10, "platform")
    away = _step(20, "yoke")
    schedule = SchedulerResult(ranked_steps=[away, home], selected_step=away)
    apply_workspace_home_filter(schedule, home_project_id=2, conn=None)
    assert [step.item_id for step in schedule.ranked_steps] == [10]
    assert schedule.selected_step is not None
    assert schedule.selected_step.item_id == 10
    assert schedule.workspace_home_project == "platform"
    assert schedule.runnable_elsewhere[0]["project"] == "yoke"
    assert schedule.runnable_elsewhere[0]["count"] == 1


def test_unmapped_home_assigns_nothing() -> None:
    away = _step(20, "yoke")
    schedule = SchedulerResult(ranked_steps=[away], selected_step=away)
    apply_workspace_home_filter(schedule, home_project_id=None, conn=None)
    assert schedule.ranked_steps == []
    assert schedule.selected_step is None
    assert schedule.runnable_elsewhere[0]["project"] == "yoke"


def test_live_claimed_elsewhere_is_not_offered() -> None:
    held = _step(20, "yoke", assignable=False)
    schedule = SchedulerResult(ranked_steps=[held], selected_step=None)
    apply_workspace_home_filter(schedule, home_project_id=2, conn=None)
    assert schedule.runnable_elsewhere == []


def test_elsewhere_wait_beats_local_blockers() -> None:
    frontier = FrontierState(
        runnable_items=[],
        blocked_items=["PLAT-1"],
        sml_coherent=True,
        runnable_elsewhere=[
            {
                "project": "yoke",
                "project_id": 1,
                "count": 1,
                "item_refs": ["YOK-20"],
                "checkout_path": "/Users/bee/yoke",
            }
        ],
        workspace_home_project="platform",
    )
    result = decide_next_action(_offer(), frontier)
    assert result.action == ActionKind.WAIT
    assert result.context["wait_reason"] == "runnable_elsewhere"
    assert "YOK-20" in result.reason
    assert "/Users/bee/yoke" in result.reason


def test_home_runnable_still_charges() -> None:
    frontier = FrontierState(
        runnable_items=["PLAT-9"],
        selected_item="PLAT-9",
        sml_coherent=True,
        runnable_elsewhere=[{"project": "yoke", "count": 1, "item_refs": ["YOK-20"]}],
        workspace_home_project="platform",
    )
    result = decide_next_action(_offer(), frontier)
    assert result.action == ActionKind.CHARGE
    assert result.context["selected_item"] == "PLAT-9"


def test_existing_path_without_mapping_is_unmapped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.machine_config.project_id",
        lambda *_a, **_k: None,
    )
    assert resolve_offer_home_project(SimpleNamespace(), workspace=str(tmp_path)) is None


def test_missing_path_falls_back_to_session_project() -> None:
    conn = SimpleNamespace(
        execute=lambda *_a, **_k: SimpleNamespace(
            fetchone=lambda: {"project_id": 7},
        )
    )
    assert resolve_offer_home_project(
        conn, workspace="/no/such/checkout/on/this/box", session_id="sess",
    ) == 7


def test_item_or_project_override_skips_home_filter() -> None:
    assert workspace_home_filter_requested() is True
    assert workspace_home_filter_requested(project_override=["yoke"]) is False
    assert workspace_home_filter_requested(item="YOK-20") is False


def test_enrich_fills_blank_checkout_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
        lambda pid: "/Users/bee/yoke" if int(pid) == 1 else None,
    )
    payload = {
        "context": {
            "workspace_home_project": "platform",
            "workspace_unmapped": False,
            "runnable_elsewhere": [
                {
                    "project": "yoke",
                    "project_id": 1,
                    "count": 1,
                    "item_refs": ["YOK-20"],
                    "checkout_path": "",
                }
            ],
            "runnable_elsewhere_note": "nothing runnable in platform; 1 runnable in yoke (YOK-20) — invoke /yoke do from the yoke checkout",
        }
    }
    enrich_elsewhere_checkout_paths(payload)
    group = payload["context"]["runnable_elsewhere"][0]
    assert group["checkout_path"] == "/Users/bee/yoke"
    assert "/Users/bee/yoke" in payload["context"]["runnable_elsewhere_note"]


def test_elsewhere_note_teaches_the_checkout_recipe() -> None:
    note = render_runnable_elsewhere_note(
        [
            {
                "project": "yoke",
                "count": 2,
                "item_refs": ["YOK-1", "YOK-2"],
                "checkout_path": "/Users/bee/yoke",
            }
        ],
        home_project="platform",
        unmapped=False,
    )
    assert note.startswith("nothing runnable in platform")
    assert "invoke /yoke do from /Users/bee/yoke" in note
