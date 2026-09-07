"""Status reports doctor-backed health from the last receipt, never inline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_cli.config.status_doctor import attach_doctor, _age_label, _summarize
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
                "scope": "quick",
                "fail_count": 2,
                "pass_count": 40,
                "warn_count": 6,
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
    assert report["doctor"]["summary"].startswith("2 FAIL / 40 PASS / 6 WARN")
    assert "quick scope" in report["doctor"]["summary"]
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


def _receipt(scope, **counts):
    base = {
        "never_run": False,
        "ran_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "fail_count": 0,
        "pass_count": 0,
        "warn_count": 0,
    }
    base.update(counts)
    if scope is not None:
        base["scope"] = scope
    return base


def test_narrow_only_run_is_labelled_as_not_whole_machine() -> None:
    summary = _summarize(_receipt("only"))
    assert summary.startswith("0 FAIL / 0 PASS / 0 WARN")
    assert "narrow --only run (not whole-machine)" in summary


def test_quick_and_full_runs_name_their_own_scope() -> None:
    assert "quick scope" in _summarize(_receipt("quick", fail_count=5, pass_count=13))
    assert "full scope" in _summarize(_receipt("full", pass_count=90))


def test_warnings_are_reported_rather_than_hidden() -> None:
    summary = _summarize(_receipt("quick", fail_count=5, pass_count=13, warn_count=6))
    assert "5 FAIL / 13 PASS / 6 WARN" in summary


def test_missing_scope_is_reported_honestly() -> None:
    assert "scope not recorded (coverage unknown)" in _summarize(_receipt(None))
    assert "scope not recorded (coverage unknown)" in _summarize(_receipt(""))


def test_unknown_scope_is_not_claimed_as_whole_machine() -> None:
    summary = _summarize(_receipt("targeted"))
    assert "targeted scope (not whole-machine)" in summary
