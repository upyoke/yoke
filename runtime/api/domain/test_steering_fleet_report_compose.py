"""Held-scope composition: one report from every live steering claim."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
    seed_strategy_doc,
)
from yoke_core.domain.steering_fleet_plan_capacity import PLAN_LIMIT_HEADING
from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport
from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    SurfaceReadiness,
)
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
    combined_body,
    combined_dict,
    compose_held_reports,
    steering_scope_descriptor,
)
from yoke_core.domain.steering_fleet_report_inbox import UnackedInjectedMessage
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_render import (
    LAUNCH_BALANCE_NOTE,
    REPORT_PREAMBLE,
)


NOW = "2026-08-29T12:00:00Z"


def _report(
    project_id: int,
    now: str,
    *,
    idle: tuple[ClaimHolder, ...] = (),
    launchable: tuple[SurfaceReadiness, ...] = (),
    session_counts: tuple[SessionCount, ...] = (),
    origin_counts: tuple[tuple[str, int], ...] = (),
    plan_limits: tuple[MachinePlanLimit, ...] = (),
) -> FleetReport:
    return FleetReport(
        project_id=project_id,
        composed_at=now,
        staffing_after_seconds=60,
        idle_after_seconds=60,
        available=(),
        holders=(),
        idle=idle,
        starved=(),
        unregistered_launches=(),
        landed_open=(),
        dead_waits=(),
        launchable=launchable,
        session_counts=session_counts,
        origin_counts=origin_counts,
        plan_limits=plan_limits,
    )


def _idle(project_id: int) -> ClaimHolder:
    return ClaimHolder(
        session_id=f"idle-{project_id}",
        item_id=project_id,
        public_ref=f"X-{project_id}",
        mode="wait",
        parked=False,
        last_activity_at="2026-08-29T11:00:00Z",
        idle_seconds=3600,
    )


def _patch_compose(monkeypatch, factory) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.steering_fleet_report.compose_report",
        factory,
    )


def test_descriptor_uses_project_slug_today_and_canonical_json_otherwise(
    test_db,
) -> None:
    seed_standard_steering_world(test_db)

    assert steering_scope_descriptor(test_db, {"project_id": PROJECT_ALPHA}) == "alpha"
    assert steering_scope_descriptor(test_db, {"area": "qa"}) == '{"area":"qa"}'
    assert (
        steering_scope_descriptor(
            test_db, {"project_id": PROJECT_ALPHA, "document": "AREA-PLAN"}
        )
        == "alpha · AREA-PLAN"
    )


def test_a_document_seat_composes_its_own_scope_section(test_db, monkeypatch) -> None:
    """The seat's own scope reaches the report, so it can narrow the rows."""
    seed_standard_steering_world(test_db)
    seed_strategy_doc(test_db, PROJECT_ALPHA, "AREA-PLAN")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA, document="AREA-PLAN")
    seen: list[dict] = []

    def factory(conn, **kwargs):
        seen.append(dict(kwargs.get("scope") or {}))
        return _report(kwargs["project_id"], kwargs["now"])

    _patch_compose(monkeypatch, factory)

    combined = compose_held_reports(test_db, session_id=SESSION_ALPHA, now=NOW)

    assert seen == [{"project_id": PROJECT_ALPHA, "document": "AREA-PLAN"}]
    assert [section.descriptor for section in combined.sections] == [
        "alpha · AREA-PLAN"
    ]


def test_two_held_scopes_become_two_named_sections(test_db, monkeypatch) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)
    _patch_compose(
        monkeypatch,
        lambda _conn, *, project_id, now, **_k: _report(project_id, now),
    )

    combined = compose_held_reports(test_db, session_id=SESSION_ALPHA, now=NOW)

    assert [section.descriptor for section in combined.sections] == ["alpha", "beta"]
    assert combined.unacked_injected == ()
    body = combined_body(combined)
    assert body.index("## alpha") < body.index("## beta")
    assert "2 held scopes" in body


def test_actionable_scopes_sort_before_quiet_ones(test_db, monkeypatch) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)

    def factory(_conn, *, project_id, now, **_kwargs):
        idle = (_idle(project_id),) if project_id == PROJECT_BETA else ()
        return _report(project_id, now, idle=idle)

    _patch_compose(monkeypatch, factory)

    combined = compose_held_reports(test_db, session_id=SESSION_ALPHA, now=NOW)

    assert [section.descriptor for section in combined.sections] == ["beta", "alpha"]
    assert combined.actionable is True
    assert combined.sections[0].report.actionable is True
    assert combined.sections[1].report.actionable is False


def test_explicit_project_filter_selects_the_matching_claim(
    test_db, monkeypatch
) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)
    _patch_compose(
        monkeypatch,
        lambda _conn, *, project_id, now, **_k: _report(project_id, now),
    )

    combined = compose_held_reports(
        test_db,
        session_id=SESSION_ALPHA,
        now=NOW,
        project_id=PROJECT_ALPHA,
    )

    assert [section.descriptor for section in combined.sections] == ["alpha"]


def test_a_change_in_either_scope_changes_the_combined_fingerprint(
    test_db, monkeypatch
) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)
    _patch_compose(
        monkeypatch,
        lambda _conn, *, project_id, now, **_k: _report(project_id, now),
    )
    before = compose_held_reports(
        test_db, session_id=SESSION_ALPHA, now=NOW
    ).fingerprint()

    def later(_conn, *, project_id, now, **_kwargs):
        idle = (_idle(project_id),) if project_id == PROJECT_BETA else ()
        return _report(project_id, now, idle=idle)

    _patch_compose(monkeypatch, later)
    after = compose_held_reports(
        test_db, session_id=SESSION_ALPHA, now=NOW
    ).fingerprint()

    assert before != after


def _ready(machine_id: str, surface: str = "codex-cli") -> SurfaceReadiness:
    return SurfaceReadiness(machine_id=machine_id, surface=surface)


def _count(machine_id: str, count: int) -> SessionCount:
    return SessionCount(
        machine_id,
        "codex-cli",
        count,
        "gpt-5.6-sol",
        "high",
        None,
        "gpt-5.6-sol",
        "high",
        None,
    )


def _limit(machine_id: str) -> MachinePlanLimit:
    return MachinePlanLimit(
        machine_id=machine_id,
        machine_name="host-a",
        surface="codex-cli",
        plan_tier="pro",
        window_kind="monthly",
        scope="all",
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
