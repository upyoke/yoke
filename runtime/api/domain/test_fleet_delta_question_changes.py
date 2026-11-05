"""Polling questions wakes immediately and retains ambient session identity."""

import io

from runtime.api.domain.test_fleet_delta_probe import (
    _ok,
    _policy,
    _report,
    _Clock,
    REPORT_DIGEST,
    PROJECT_POLICY_FUNCTION,
    STEERING_REPORT_FUNCTION,
    ENVELOPES_FUNCTION,
    fleet_delta_probe,
    run,
    Any,
)


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
    assert seen[0] == (f"fleet inbox m state=pending from=w\n{REPORT_DIGEST}\n")


def test_question_edges_request_a_report_before_cooldown():
    question_states = iter(({"17": "pending"}, {"17": "resolved"}, {}))
    requests = []
    previous_ids = []

    def call(function, payload):
        if function == STEERING_REPORT_FUNCTION:
            if payload.get("questions_only"):
                previous_ids.append(payload["previous_question_ids"])
                return _ok({"question_states": next(question_states)})
            requests.append(payload)
            return _report(str(len(requests)))
        return _policy(30) if function == PROJECT_POLICY_FUNCTION else _ok({})

    out = io.StringIO()
    assert (
        run(
            ["project"],
            out=out,
            call=call,
            clock=_Clock(),
            sleep=lambda _: None,
            duration=180,
            session_id="steerer",
        )
        == 0
    )
    assert out.getvalue().count("fleet question 17 pending") == 1
    assert out.getvalue().count("fleet question 17 resolved") == 1
    assert requests == [{"deliver": True, "question_change": True}] * 2
    assert previous_ids == [[], [17], []]
