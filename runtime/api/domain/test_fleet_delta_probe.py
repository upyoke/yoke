"""The polling loop: silence, read composition, and failure handling."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from yoke_core.domain import fleet_delta_probe
from yoke_core.domain.fleet_delta_probe import (
    MAX_CONSECUTIVE_READ_FAILURES,
    PROJECT_POLICY_FUNCTION,
    READ_FAILURE_EXIT,
    STEERING_REPORT_FUNCTION,
    run,
)
from yoke_core.domain.fleet_delta_snapshot import (
    ENVELOPES_FUNCTION,
    FRONTIER_FUNCTION,
    SESSIONS_FUNCTION,
)

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
REPORT_BODY = "fleet report\n  one composed picture"


def _ok(result: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(success=True, result=result, error=None)


def _failure(code: str, message: str) -> SimpleNamespace:
    return SimpleNamespace(
        success=False,
        result=None,
        error=SimpleNamespace(code=code, message=message),
    )


def _policy(interval_minutes: int = 2) -> SimpleNamespace:
    return _ok(
        {
            "settings_json": json.dumps(
                {"steering_report_interval_minutes": interval_minutes}
            )
        }
    )


def _report(fingerprint: str = "fleet-a") -> SimpleNamespace:
    return _ok({"fingerprint": fingerprint, "body": REPORT_BODY})


class _Clock:
    """Advances one interval per read so a bounded run terminates."""

    def __init__(self, step_seconds: int = 60) -> None:
        self.now = NOW
        self.step = timedelta(seconds=step_seconds)

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


def _drive(responses: list[Any], **kwargs: Any) -> tuple[int, str, list[str]]:
    """Run the loop against a scripted response sequence."""
    calls: list[str] = []
    remaining = list(responses)

    def call(function_id: str, payload: dict[str, Any]) -> Any:
        calls.append(function_id)
        return remaining.pop(0) if remaining else _ok({})

    out = io.StringIO()
    code = run(
        ["yoke"],
        out=out,
        call=call,
        clock=_Clock(),
        sleep=lambda _seconds: None,
        session_id="steerer-0000",
        **kwargs,
    )
    return code, out.getvalue(), calls


def test_one_pass_reads_the_three_registered_functions() -> None:
    code, output, calls = _drive([], duration=1)
    assert code == 0
    assert calls == [SESSIONS_FUNCTION, FRONTIER_FUNCTION, ENVELOPES_FUNCTION]
    assert output == ""


def test_heartbeat_only_quiet_passes_do_not_fetch_a_report() -> None:
    roster = _ok({"rows": [{"session_id": "a", "activity_at": "2026-08-28T17:00:00Z"}]})
    frontier = _ok({"ranked_steps": [{"item_id": "YOK-1", "status": "idea"}]})
    envelopes = _ok({"messages": []})
    code, output, calls = _drive(
        [roster, frontier, envelopes, roster, frontier, envelopes],
        duration=90,
    )
    assert code == 0
    assert output == ""
    assert STEERING_REPORT_FUNCTION not in calls


def test_a_status_change_appends_the_composed_report_after_the_delta() -> None:
    roster = _ok({"rows": []})
    envelopes = _ok({"messages": []})
    code, output, _ = _drive(
        [
            roster,
            _ok({"ranked_steps": [{"item_id": "YOK-1", "status": "idea"}]}),
            envelopes,
            roster,
            _ok({"ranked_steps": [{"item_id": "YOK-1", "status": "implementing"}]}),
            envelopes,
            _policy(),
            _report(),
        ],
        duration=90,
    )
    assert code == 0
    assert output == (f"fleet item YOK-1 status idea -> implementing\n{REPORT_BODY}\n")


def test_an_unchanged_report_is_not_reprinted_after_the_rate_limit() -> None:
    roster = _ok({"rows": []})
    envelopes = _ok({"messages": []})
    code, output, calls = _drive(
        [
            roster,
            _ok({"ranked_steps": [{"item_id": "YOK-1", "status": "idea"}]}),
            envelopes,
            roster,
            _ok({"ranked_steps": [{"item_id": "YOK-1", "status": "implementing"}]}),
            envelopes,
            _policy(),
            _report(),
            roster,
            _ok(
                {
                    "ranked_steps": [
                        {"item_id": "YOK-1", "status": "reviewing-implementation"}
                    ]
                }
            ),
            envelopes,
            _policy(),
            roster,
            _ok(
                {
                    "ranked_steps": [
                        {"item_id": "YOK-1", "status": "polishing-implementation"}
                    ]
                }
            ),
            envelopes,
            _policy(),
            _report(),
        ],
        duration=210,
    )

    assert code == 0
    assert calls.count(STEERING_REPORT_FUNCTION) == 2
    assert output.count(REPORT_BODY) == 1


def test_a_transient_read_failure_is_named_and_the_loop_continues() -> None:
    code, output, _ = _drive(
        [
            _failure("https_transport_failed", "unreachable"),
            _ok({"rows": []}),
            _ok({"ranked_steps": []}),
            _ok({"messages": []}),
        ],
        duration=90,
    )
    assert code == 0
    assert "fleet ERROR read failed sessions.list" in output
    assert "attempt 1/" in output
    assert "FATAL" not in output


def test_repeated_read_failures_stop_instead_of_hanging_silent() -> None:
    code, output, _ = _drive(
        [_failure("https_transport_failed", "unreachable")] * 6,
        duration=0,
    )
    assert code == READ_FAILURE_EXIT
    assert "fleet FATAL read failed sessions.list" in output
    assert f"{MAX_CONSECUTIVE_READ_FAILURES} consecutive failures" in output
    assert output.count("fleet ERROR") == MAX_CONSECUTIVE_READ_FAILURES - 1


def test_a_non_positive_interval_is_a_usage_error() -> None:
    assert fleet_delta_probe.main(["--interval", "0"]) == 2


def test_projects_default_to_the_checkout_project(monkeypatch: Any) -> None:
    monkeypatch.setenv("YOKE_PROJECT", "yoke")
    assert fleet_delta_probe.resolve_projects(None) == ["yoke"]
    assert fleet_delta_probe.resolve_projects(["platform"]) == ["platform"]


def test_the_session_id_is_resolved_from_ambient_identity(monkeypatch: Any) -> None:
    """Nothing passes the steerer's id in, so a handoff needs no edit."""
    monkeypatch.setattr(
        fleet_delta_probe, "ambient_session_id", lambda: "resolved-0000"
    )
    seen: list[str] = []

    def call(function_id: str, payload: dict[str, Any]) -> Any:
        if function_id == PROJECT_POLICY_FUNCTION:
            return _policy()
        if function_id == STEERING_REPORT_FUNCTION:
            return _report()
        if function_id == ENVELOPES_FUNCTION:
            return _ok(
                {
                    "messages": [
                        {
                            "message_id": "m",
                            "sender_session_id": "w",
                            "created_at": "2026-08-28T17:00:00Z",
                            "recipients": [
                                {"session_id": "resolved-0000", "state": "pending"},
                                {"session_id": "another-0000", "state": "pending"},
                            ],
                        }
                    ]
                }
            )
        return _ok({})

    out = io.StringIO()
    run(
        ["yoke"],
        out=out,
        call=call,
        clock=_Clock(),
        sleep=lambda _seconds: None,
        duration=90,
    )
    seen.append(out.getvalue())
    # Only the envelope addressed to the resolved session is reported, and
    # the second pass is what compares it against the first.
    assert seen[0] == (f"fleet inbox m state=pending from=w\n{REPORT_BODY}\n")
