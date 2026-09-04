"""Combined steering-report machine facts, identity, and inbox output."""

from __future__ import annotations

import hashlib
import json

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
from yoke_core.domain.steering_fleet_report_inbox import UnackedInjectedMessage
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_render import (
    LAUNCH_BALANCE_NOTE,
    REPORT_PREAMBLE,
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
        resets_at="2026-09-30T00:00:00Z",
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
    assert body.count(LAUNCH_BALANCE_NOTE) == 1
    assert body.count(PLAN_LIMIT_HEADING) == 1
    assert REPORT_PREAMBLE not in body
    assert body.index("## alpha") < body.index("## beta")
    assert body.index("## beta") < body.index("launchable machine/surface pairs:")
    before_beta, after_beta = body.split("## beta", 1)
    assert "codex-cli 2" in before_beta
    assert "origin steering 2" in before_beta
    assert LAUNCH_BALANCE_NOTE not in before_beta
    assert "codex-cli 5" in after_beta
    assert "origin operator 1" in after_beta


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
    assert body.count(LAUNCH_BALANCE_NOTE) == 2
    assert body.index("machine-a/codex-cli") < body.index("machine-b/codex-cli")
    assert body.index("## beta") < body.index("machine-a/codex-cli")


def test_combined_fingerprint_is_the_per_scope_hashes_not_the_body() -> None:
    combined = _combined(
        ScopedFleetReport("alpha", _report(1, NOW, launchable=(_ready("machine-a"),))),
        ScopedFleetReport("beta", _report(2, NOW, launchable=(_ready("machine-a"),))),
    )
    encoded = json.dumps(
        [
            *[
                (section.descriptor, section.report.fingerprint())
                for section in combined.sections
            ],
            ("unacked_injected", []),
        ],
        separators=(",", ":"),
    )
    assert combined.fingerprint() == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert combined_body(combined) not in encoded


def test_combined_dict_keeps_machine_facts_on_each_scope() -> None:
    payload = combined_dict(
        _combined(
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
    )
    assert payload["unacked_injected"] == []
    assert payload["scopes"][0]["launchable"] == [
        {"machine_id": "machine-a", "surface": "codex-cli"}
    ]
    assert payload["scopes"][0]["plan_limits"]


def test_unacked_injected_makes_a_quiet_combined_report_actionable() -> None:
    combined = CombinedFleetReport(
        composed_at=NOW,
        sections=(ScopedFleetReport("alpha", _report(1, NOW)),),
        unacked_injected=(
            UnackedInjectedMessage(
                message_id="11111111-2222-4333-8444-555555555555",
                last_injected_at="2026-08-29T11:00:00Z",
                age_seconds=3600,
            ),
        ),
    )
    assert not combined.sections[0].report.actionable
    assert combined.actionable
    body = combined_body(combined)
    assert "unacked injected (this session)" in body
    assert "yoke messages acknowledge 11111111-2222-4333-8444-555555555555" in body
