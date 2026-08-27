"""CLI contracts for permanent session termination."""

from __future__ import annotations

from types import SimpleNamespace
import io

from yoke_cli.commands.adapters import session_control_roster as roster
from yoke_cli.commands.adapters import session_control_termination as termination
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY,
    SESSION_CONTROL_SUBCOMMAND_REGISTRY,
)


def test_sessions_terminate_dispatches_registered_global_operation(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        termination,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    result = termination.session_terminate(
        [
            "worker-session",
            "--reason",
            "worker completed",
            "--session-id",
            "steering-session",
        ]
    )

    assert result == 0
    assert calls[0]["function_id"] == "session_control.session.terminate"
    assert calls[0]["target"].kind == "global"
    assert calls[0]["session_id"] == "steering-session"
    assert calls[0]["payload"] == {
        "session_id": "worker-session",
        "reason": "worker completed",
        "override_chain_end": False,
    }


def test_chain_override_carries_a_required_audit_rationale(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        termination,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    assert (
        termination.session_terminate(
            [
                "worker-session",
                "--reason",
                "abort",
                "--override-chain-end",
                "--chain-end-rationale",
                "steering intentionally abandons this chain",
            ]
        )
        == 0
    )
    assert calls[0]["payload"]["override_chain_end"] is True
    assert calls[0]["payload"]["chain_end_rationale"] == (
        "steering intentionally abandons this chain"
    )


def test_chain_override_without_rationale_is_a_usage_error(capsys) -> None:
    assert (
        termination.session_terminate(
            [
                "worker-session",
                "--reason",
                "abort",
                "--override-chain-end",
            ]
        )
        == 2
    )
    assert "requires --chain-end-rationale" in capsys.readouterr().err


def test_canonical_and_sessions_routes_share_the_termination_adapter() -> None:
    canonical = SESSION_CONTROL_SUBCOMMAND_REGISTRY[
        ("session-control", "session", "terminate")
    ]
    alias = SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY[("sessions", "terminate")]
    assert (
        canonical
        == alias
        == (
            "session_control.session.terminate",
            termination.session_terminate,
        )
    )


def test_human_output_names_terminal_effects() -> None:
    stdout = io.StringIO()
    termination._write_termination_result(
        SimpleNamespace(
            result={
                "session": {
                    "session_id": "worker-session",
                    "terminated_at": "2026-08-26T12:00:00Z",
                },
                "cancelled_recipient_count": 3,
                "reap_state": "pending",
                "deduplicated": False,
            }
        ),
        stdout,
        io.StringIO(),
    )
    rendered = stdout.getvalue()
    assert rendered.startswith("SESSION TERMINATION\n")
    for expected in ("worker-session", "CANCELLED RECIPIENTS", "pending"):
        assert expected in rendered


def test_sessions_list_narrows_kills_through_ended_cause(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        roster,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    assert roster.session_control_roster_list(["--ended-cause", "killed"]) == 0
    assert calls[0]["payload"] == {"ended_cause": "killed"}


def test_sessions_list_rejects_terminated_as_a_liveness_peer(capsys) -> None:
    assert roster.session_control_roster_list(["--liveness", "terminated"]) == 2
    stderr = capsys.readouterr().err
    assert "invalid choice: 'terminated'" in stderr
    assert "--ended-cause killed|wound_down" in stderr
