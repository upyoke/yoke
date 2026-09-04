"""Held-scope composition: one report from every live steering claim."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
    seed_strategy_doc,
)
from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport
from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    SurfaceReadiness,
)
from yoke_core.domain.steering_fleet_report_compose import (
    combined_body,
    compose_held_reports,
    steering_scope_descriptor,
)
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit


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
