"""Agent setup ends with this session's readiness check before onboarding."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import doctor, doctor_install
from yoke_cli.config import setup_facts_summary
from yoke_cli.config.setup_agent_answering import AnswerFlow

ACTION = {
    "row_id": "lifecycle-readiness",
    "title": "First work",
    "status": "unknown",
    "reason": "first_item_not_done",
    "command": "/yoke steer CURRENT-PLAN",
    "home": ".yoke/docs/start/terminal-onboarding.md",
}


@pytest.fixture(autouse=True)
def current_setup_facts(monkeypatch):
    monkeypatch.setattr(
        setup_facts_summary,
        "read_project",
        lambda *_a, **_kw: {
            "lines": ["Setup: 9 configured"],
            "next_action": ACTION,
        },
    )


def _done(checkout: Path | None) -> dict:
    flow = SimpleNamespace(
        result=SimpleNamespace(
            path_repair=None,
            project_checkout=str(checkout) if checkout else "",
        ),
        report_path="",
    )
    return AnswerFlow._done_fields(flow)


def test_a_session_in_the_project_checks_itself_then_follows_current_action(
    tmp_path, monkeypatch
):
    checkout = tmp_path / "demo"
    (checkout / "src").mkdir(parents=True)
    monkeypatch.chdir(checkout / "src")
    steps = _done(checkout)["next"]
    assert len(steps) == 2
    assert "doctor run --session`" in steps[0]
    assert steps[
        1
    ] == "After session readiness passes: " + setup_facts_summary.next_line(ACTION)
    assert _done(checkout)["next_action"] == ACTION


def test_a_session_elsewhere_opens_the_project_folder(tmp_path, monkeypatch):
    checkout = tmp_path / "demo"
    checkout.mkdir()
    monkeypatch.chdir(tmp_path)
    steps = _done(checkout)["next"]
    assert steps[0] == f"Open Claude Code, Codex or Cursor in {checkout}."
    assert "doctor run --session" in steps[1]
    assert steps[
        2
    ] == "After session readiness passes: " + setup_facts_summary.next_line(ACTION)
    assert _done(checkout)["next_action"] == ACTION


def test_absent_server_next_action_never_guesses_onboarding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        setup_facts_summary,
        "read_project",
        lambda *_a, **_kw: {
            "lines": ["Setup: 9 configured"],
            "next_action": None,
        },
    )
    result = _done(tmp_path)
    assert "doctor run --session" in result["next"][0]
    assert result["next_action"] is None
    assert not any(
        "/yoke onboard" in step or "Next:" in step for step in result["next"]
    )


def test_machine_only_setup_has_no_readiness_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    steps = _done(None)["next"]
    assert not any("--session" in step for step in steps)


def test_session_scope_selects_only_the_session_roster(monkeypatch):
    captured = {}
    monkeypatch.setattr(doctor, "required_project_context", lambda p: "42")
    monkeypatch.setattr(doctor, "_active_transport_is_https", lambda: False)
    monkeypatch.setattr(doctor, "_runtime_for_active_connection", lambda: "local")
    monkeypatch.setattr(
        doctor, "_dispatch_in_process", lambda **kwargs: captured.update(kwargs) or 0
    )
    assert doctor.doctor_run(["--session"]) == 0
    assert captured["payload"]["only"] == ",".join(doctor_install.session_slugs())
    assert doctor.doctor_run(["--session", "--install"]) == 2
