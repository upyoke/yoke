"""Authorization coverage for the on-demand steering fleet report."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
from yoke_core.domain.handlers.steering_report import handle_get
from yoke_core.domain.steering_fleet_report import FleetReport


class _KeepOpenConnection:
    """Let the handler close its connection without closing the fixture."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _request(project_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="steering.report.get",
        actor=ActorContext(actor_id="2", session_id=SESSION_ALPHA),
        target=TargetRef(kind="global"),
        payload={},
        options={"authorized_project_id": project_id},
    )


def _empty_report(project_id: int, now: str) -> FleetReport:
    return FleetReport(
        project_id=project_id,
        composed_at=now,
        staffing_after_seconds=60,
        idle_after_seconds=60,
        available=(),
        holders=(),
        idle=(),
        starved=(),
        unregistered_launches=(),
        landed_open=(),
        dead_waits=(),
        launchable=(),
        session_counts=(),
    )


def _patch_report_dependencies(monkeypatch, test_db) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: _KeepOpenConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_settings.get_project_int_for_id",
        lambda *_args: 1,
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_store.utc_now",
        lambda: "2026-08-29T12:00:00Z",
    )
    monkeypatch.setattr(
        "yoke_core.domain.steering_fleet_report.compose_report",
        lambda _conn, *, project_id, now, **_kwargs: _empty_report(project_id, now),
    )


def test_report_accepts_each_requested_project_claim(test_db, monkeypatch) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)
    _patch_report_dependencies(monkeypatch, test_db)

    for project_id in (PROJECT_ALPHA, PROJECT_BETA):
        outcome = handle_get(_request(project_id))

        assert outcome.primary_success
        assert outcome.result_payload["project_id"] == project_id


def test_report_refuses_without_the_requested_project_claim(
    test_db,
    monkeypatch,
) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
    _patch_report_dependencies(monkeypatch, test_db)

    outcome = handle_get(_request(PROJECT_BETA))

    assert not outcome.primary_success
    assert outcome.error.code == "steering_claim_required"
    assert (
        f"yoke claims steering acquire --project {PROJECT_BETA} "
        f"--doc {DEFAULT_STEERING_DOC_SLUG}" in outcome.error.message
    )
