"""Question commands preserve requester, options and immutable replacement."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import decision_request_questions as adapter


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        adapter, "dispatch_and_emit", lambda **kwargs: recorded.append(kwargs) or 0
    )
    return recorded


def test_ask_options_recommendation_replacement_and_requester(tmp_path, calls):
    context = tmp_path / "context.md"
    context.write_text("The header uses **blue**.")
    assert (
        adapter.decision_requests_ask(
            [
                "--session",
                "requesting-worker",
                "--key",
                "color",
                "--question",
                "Which color?",
                "--option",
                "blue=Blue::Matches the header",
                "--recommend",
                "blue",
                "--no-freeform",
                "--context-file",
                str(context),
                "--replaces",
                "17",
                "--to",
                "301",
                "--to",
                "Jane Doe",
                "--audience",
                "Reviewers",
                "--project",
                "transaction-intelligence",
                "--json",
            ]
        )
        == 0
    )
    call = calls[0]
    assert call["payload"]["to"] == ["301", "Jane Doe"]
    assert call["payload"]["audience"] == "Reviewers"
    assert call["payload"]["project"] == "transaction-intelligence"
    assert call["function_id"] == "decision_requests.ask"
    assert call["payload"]["requesting_session_id"] == "requesting-worker"
    assert call["payload"]["replaces"] == 17
    assert call["payload"]["options"] == [
        {"id": "blue", "label": "Blue", "detail": "Matches the header"}
    ]
    assert not call["payload"]["allow_freeform"]
    assert "**blue**" in call["payload"]["context"]


def test_ask_defaults_requester_to_calling_session(calls):
    assert (
        adapter.decision_requests_ask(["--key", "next", "--question", "What next?"])
        == 0
    )
    assert calls[0]["payload"]["requesting_session_id"] is None
    assert calls[0]["payload"]["project"] is None
    assert calls[0]["payload"]["allow_freeform"]


def test_list_mine_and_explicit_requester_are_distinct(calls):
    assert adapter.decision_requests_list(["--mine"]) == 0
    assert calls[-1]["payload"]["requesting_session_id"] is None
    assert (
        adapter.decision_requests_list(
            ["--requesting-session", "worker", "--status", "withdrawn"]
        )
        == 0
    )
    assert calls[-1]["payload"] == {
        "requesting_session_id": "worker",
        "status": "withdrawn",
    }


def test_withdraw_keeps_cancellation_reason(calls):
    assert (
        adapter.decision_requests_withdraw(["17", "--reason", "Direction changed"]) == 0
    )
    assert calls[0]["function_id"] == "decision_requests.withdraw"
    assert calls[0]["payload"] == {"request_id": 17, "reason": "Direction changed"}


def test_option_requires_id_equals_label(calls):
    assert (
        adapter.decision_requests_ask(
            ["--key", "color", "--question", "Which color?", "--option", "Blue"]
        )
        == 2
    )
    assert calls == []


def test_missing_attachment_refuses_before_dispatch(calls, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        adapter.decision_requests_ask(
            [
                "--key",
                "review",
                "--question",
                "Which header?",
                "--attach",
                str(tmp_path / "missing.png"),
            ]
        )
    assert exc.value.code == 2
    assert calls == []
    assert "operator_question_attachment_missing_file" in capsys.readouterr().err


def test_ask_help_teaches_option_consequences(capsys):
    with pytest.raises(SystemExit) as exc:
        adapter.decision_requests_ask(["--help"])
    assert exc.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "Write DETAIL as what happens if the user picks this option, in plain words." in output
