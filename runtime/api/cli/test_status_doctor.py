"""Status reports doctor-backed health from the last receipt, never inline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_cli.config.status_doctor import attach_doctor, _age_label
from yoke_contracts.api.function_call import FunctionCallResponse


def test_unverified_when_the_plane_is_unreachable() -> None:
    report = attach_doctor(
        {"server": {"reachable": False}, "db": {"relevant": False, "ok": False}},
    )
    assert report["doctor"]["summary"].startswith("health unverified")


def test_receipt_line_does_not_flip_ok(monkeypatch) -> None:
    ran_at = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def _last_run(**_kwargs):
        return FunctionCallResponse(
            success=True,
            function="doctor.last_run.get",
            version="v1",
            request_id="r1",
            result={
                "never_run": False,
                "ran_at": ran_at,
                "fail_count": 2,
                "pass_count": 40,
            },
        )

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        _last_run,
    )
    report = attach_doctor(
        {
            "ok": True,
            "server": {"reachable": True},
            "project": {"project_id": 1},
        }
    )
    assert report["ok"] is True
    assert report["doctor"]["summary"].startswith("2 FAIL / 40 PASS")
    assert "run yoke doctor run --quick" in report["doctor"]["summary"]


def test_never_run_is_unverified(monkeypatch) -> None:
    def _empty(**_kwargs):
        return FunctionCallResponse(
            success=True,
            function="doctor.last_run.get",
            version="v1",
            request_id="r1",
            result={"never_run": True},
        )

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        _empty,
    )
    report = attach_doctor({"server": {"reachable": True}})
    assert report["doctor"]["summary"].startswith("health unverified")


def test_age_label_hours() -> None:
    ran_at = (datetime.now(timezone.utc) - timedelta(hours=3, minutes=10)).isoformat()
    assert _age_label(ran_at) == "3h ago"
