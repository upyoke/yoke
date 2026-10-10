"""Combined steering-report machine facts, identity, and inbox output."""

from __future__ import annotations

from runtime.api.domain.test_steering_fleet_report_compose import NOW, _report
from yoke_core.domain.steering_fleet_plan_capacity import PLAN_LIMIT_HEADING
from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    SurfaceReadiness,
)
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
    combined_body,
    combined_dict,
)
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_inbox import UnackedInjectedMessage
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.session_launch_level_placement import LevelPlacement
from yoke_core.domain.steering_fleet_report_levels import LEVELS_HEADING, LevelReadout
from yoke_core.domain.steering_fleet_report_render import REPORT_PREAMBLE

_READOUT = LevelReadout(
    source="universe",
    live_workers=(("codex-cli", 2),),
    levels=(("🦉", LevelPlacement("SENIOR", "universe", (), None, None, "none")),),
)


def _ready(machine_id: str, surface: str = "codex-cli") -> SurfaceReadiness:
    return SurfaceReadiness(machine_id=machine_id, surface=surface)


def _count(machine_id: str, count: int) -> SessionCount:
    return SessionCount(
        machine_id=machine_id,
        surface="codex-cli",
        count=count,
        requested_model="gpt-5.6-sol",
        requested_reasoning_effort="high",
        requested_context_window_tokens=None,
        model="gpt-5.6-sol",
        reasoning_effort="high",
        context_window_tokens=None,
    )


def _limit(machine_id: str) -> MachinePlanLimit:
    return MachinePlanLimit(
        machine_id=machine_id,
        machine_name="host-a",
        surface="codex-cli",
        plan_tier="pro",
        window_kind="monthly",
        scope="all",
        meter="rateLimitsByLimitId.codex.primary",
        remaining_percent=50.0,
        resets_at="2026-09-30T00:00:00.000000Z",
        status="ok",
        reason=None,
    )


def _combined(*sections: ScopedFleetReport) -> CombinedFleetReport:
    return CombinedFleetReport(composed_at=NOW, sections=sections)


def test_two_scopes_on_one_machine_share_one_machine_block() -> None:
    left = _report(
        1,
        NOW,
        launchable=(_ready("machine-a"),),
        session_counts=(_count("machine-a", 2),),
        origin_counts=(("steering", 2),),
        plan_limits=(_limit("machine-a"),),
    )
    right = _report(
        2,
        NOW,
        launchable=(_ready("machine-a"),),
        session_counts=(_count("machine-a", 5),),
        origin_counts=(("operator", 1),),
        plan_limits=(_limit("machine-a"),),
    )
    body = combined_body(
        _combined(ScopedFleetReport("alpha", left), ScopedFleetReport("beta", right))
    )
    assert body.count("launchable machine/surface pairs:") == 1
    assert "allocate by headroom" not in body
    assert body.count(PLAN_LIMIT_HEADING) == 1
    assert REPORT_PREAMBLE not in body
    assert body.index("## alpha") < body.index("## beta")
    assert body.index("## beta") < body.index("launchable machine/surface pairs:")
    assert body.count("launch balance ") == 1
    assert "codex-cli 7" in body
    assert "origin operator 1 · steering 2" in body


def test_document_seats_do_not_repeat_shared_facts_or_multiply_counts() -> None:
    from dataclasses import replace
    from yoke_core.domain.steering_fleet_plan_capacity import HEADROOM_LEGEND
    from yoke_core.domain.steering_fleet_report_native_models import MachineNativeModels

    report = replace(
        _report(
            1,
            NOW,
            launchable=(_ready("machine-a"),),
            session_counts=(_count("machine-a", 2),),
            origin_counts=(("steering", 2),),
            plan_limits=(_limit("machine-a"), _limit("machine-b")),
        ),
        levels=_READOUT,
        test_machines=(("test-host", "Linux"),),
        native_models=(
            MachineNativeModels(
                "machine-a",
                "host-a",
                "codex-cli",
                "ok",
                None,
                "native",
                NOW,
                1,
                ("gpt-6.1-sol",),
            ),
        ),
    )
    combined = _combined(
        *(ScopedFleetReport(f"alpha · document-{n}", report) for n in range(6))
    )
    body = combined_body(combined)
    assert body.count("launch balance ") == 1
    assert "codex-cli 2" in body and "codex-cli 12" not in body
    assert body.count("origin steering 2") == 1
    assert body.count("Test Machines:") == 1
    assert body.count("selectable models (observed natively):") == 1
    assert body.count(f"{LEVELS_HEADING} (universe)") == 1
    assert body.count(HEADROOM_LEGEND) == 1
    assert "## alpha · document-1\n\n## alpha · document-2" in body
    assert len(combined_dict(combined)["scopes"]) == 6


def test_different_project_placements_share_heading_and_keep_each_result() -> None:
    from dataclasses import replace

    left = replace(
        _report(1, NOW), levels=replace(_READOUT, unavailable="alpha denial")
    )
    right = replace(
        _report(2, NOW), levels=replace(_READOUT, unavailable="beta denial")
    )
    body = combined_body(
        _combined(ScopedFleetReport("alpha", left), ScopedFleetReport("beta", right))
    )
    assert body.count(f"{LEVELS_HEADING} (universe)") == 1
    assert "alpha denial" in body and "beta denial" in body
    assert "placement for project 2" in body


def test_two_machines_render_two_machine_blocks() -> None:
    body = combined_body(
        _combined(
            ScopedFleetReport(
                "alpha", _report(1, NOW, launchable=(_ready("machine-a"),))
            ),
            ScopedFleetReport(
                "beta", _report(2, NOW, launchable=(_ready("machine-b"),))
            ),
        )
    )
    assert body.count("launchable machine/surface pairs:") == 2
    assert "allocate by headroom" not in body
    assert body.index("machine-a/codex-cli") < body.index("machine-b/codex-cli")
    assert body.index("## beta") < body.index("machine-a/codex-cli")


def test_scopes_sharing_a_level_readout_render_it_once_after_machines() -> None:
    from dataclasses import replace

    left = replace(_report(1, NOW, launchable=(_ready("machine-a"),)), levels=_READOUT)
    right = replace(_report(2, NOW, launchable=(_ready("machine-a"),)), levels=_READOUT)
    body = combined_body(
        _combined(ScopedFleetReport("alpha", left), ScopedFleetReport("beta", right))
    )
    assert body.count(f"{LEVELS_HEADING} (universe)") == 1
    assert body.index("launchable machine/surface pairs:") < body.index(LEVELS_HEADING)
    assert "live workers: codex-cli 2" in body


def test_combined_fingerprint_ignores_sections_the_digest_does_not_show() -> None:
    """A launchable pair, balance, or plan limit moving is not a new digest."""
    before = _combined(
        ScopedFleetReport("alpha", _report(1, NOW, launchable=(_ready("machine-a"),)))
    )
    after = _combined(
        ScopedFleetReport(
            "alpha",
            _report(
                1,
                NOW,
                launchable=(_ready("machine-b"),),
                session_counts=(_count("machine-b", 3),),
                plan_limits=(_limit("machine-b"),),
            ),
        )
    )
    assert combined_body(before) != combined_body(after)
    assert combined_hook_digest(before) == combined_hook_digest(after)
    assert before.fingerprint() == after.fingerprint()


def test_combined_dict_keeps_machine_facts_on_each_scope() -> None:
    combined = _combined(
        ScopedFleetReport(
            "alpha",
            _report(
                1,
                NOW,
                launchable=(_ready("machine-a"),),
                plan_limits=(_limit("machine-a"),),
            ),
        )
    )
    payload = combined_dict(combined)
    assert payload["unacked_injected"] == []
    assert payload["scopes"][0]["launchable"] == [
        {"machine_id": "machine-a", "surface": "codex-cli"}
    ]
    assert payload["scopes"][0]["plan_limits"]
    assert payload["digest"] == combined_hook_digest(combined)
    assert "hook digest" in payload["digest"]
    assert PLAN_LIMIT_HEADING not in payload["digest"]
    assert PLAN_LIMIT_HEADING in payload["body"]


def test_unacked_injected_makes_a_quiet_combined_report_actionable() -> None:
    combined = CombinedFleetReport(
        composed_at=NOW,
        sections=(ScopedFleetReport("alpha", _report(1, NOW)),),
        unacked_injected=(
            UnackedInjectedMessage(
                message_id="11111111-2222-4333-8444-555555555555",
                last_injected_at="2026-08-29T11:00:00.000000Z",
                age_seconds=3600,
            ),
        ),
    )
    assert not combined.sections[0].report.actionable
    assert combined.actionable
    body = combined_body(combined)
    assert "unacked injected (this session)" in body
    assert "yoke messages acknowledge 11111111-2222-4333-8444-555555555555" in body
