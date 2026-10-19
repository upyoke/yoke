"""The scripted agent follows setup's agent loop and never handles a secret."""

from __future__ import annotations

import pytest

from yoke_core.domain import machine_qa_setup_agent_driver as driver


def _question(key: str, **fields: object) -> dict:
    return {"state": "question", "key": key, "question": key, **fields}


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list:
    recorded: list = []
    monkeypatch.setattr(
        driver.subprocess,
        "run",
        lambda argv, **_kw: recorded.append(("tui", argv[1:])),
    )
    return recorded


def _agent(monkeypatch: pytest.MonkeyPatch, calls: list, replies: list) -> None:
    def run(argv: list[str]) -> dict | None:
        calls.append(("agent", argv))
        return replies.pop(0)

    monkeypatch.setattr(driver, "_run_agent", run)


def test_answers_only_scripted_choices_and_reports_the_stop(
    monkeypatch: pytest.MonkeyPatch, calls: list, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(
        monkeypatch,
        calls,
        [_question("connect.machine_admission"), _question("github.machine")],
    )
    code = driver.drive(
        "http://127.0.0.1:19121",
        "github.machine",
        {"connect.machine_admission": "own"},
    )
    assert code == 0
    assert calls == [
        ("agent", ["--connect", "http://127.0.0.1:19121"]),
        ("agent", ["--answer", "connect.machine_admission=own"]),
    ]
    assert "agent-presentation-reached: github.machine" in capsys.readouterr().out


def test_a_secret_question_goes_to_the_person_in_the_wizard_then_resumes(
    monkeypatch: pytest.MonkeyPatch, calls: list
) -> None:
    _agent(
        monkeypatch,
        calls,
        [_question("connect.invite_code", secret=True), _question("github.machine")],
    )
    assert driver.drive("http://server", "github.machine", {}) == 0
    assert calls == [
        ("agent", ["--connect", "http://server"]),
        ("tui", ["setup", "--tui", "--connect", "http://server"]),
        ("agent", []),
    ]


def test_an_unscripted_question_refuses_by_name(
    monkeypatch: pytest.MonkeyPatch, calls: list, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch, calls, [_question("project.mode")])
    assert driver.drive("http://server", "github.machine", {}) == 1
    assert "setup_agent_unscripted_question" in capsys.readouterr().out


def test_a_browser_step_shows_the_link_and_match_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    driver._show(
        {
            "state": "browser",
            "human": {
                "user_code": "K7F2",
                "url": "http://server/a",
                "instructions": "x",
            },
            "guidance": "wait",
        }
    )
    out = capsys.readouterr().out
    assert "Match code: K7F2" in out and "Open: http://server/a" in out
