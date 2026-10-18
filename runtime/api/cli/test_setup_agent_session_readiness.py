"""Agent setup ends with this session's readiness check before onboarding."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters import doctor, doctor_install
from yoke_cli.config.setup_agent_answering import AnswerFlow


def _done(checkout: Path | None) -> dict:
    flow = SimpleNamespace(
        result=SimpleNamespace(
            path_repair=None,
            project_checkout=str(checkout) if checkout else "",
        ),
        report_path="",
    )
    return AnswerFlow._done_fields(flow)


def test_a_session_in_the_project_checks_itself_then_asks_once(tmp_path, monkeypatch):
    checkout = tmp_path / "demo"
    (checkout / "src").mkdir(parents=True)
    monkeypatch.chdir(checkout / "src")
    steps = _done(checkout)["next"]
    assert len(steps) == 2
    assert "doctor run --session`" in steps[0]
    assert "ask the person once" in steps[1]
    assert "/yoke onboard" in steps[1]


def test_a_session_elsewhere_opens_the_project_folder(tmp_path, monkeypatch):
    checkout = tmp_path / "demo"
    checkout.mkdir()
    monkeypatch.chdir(tmp_path)
    steps = _done(checkout)["next"]
    assert steps[0] == f"Open Claude Code, Codex or Cursor in {checkout}."
    assert "checks the session is ready first" in steps[1]
    assert not any("--session" in step for step in steps)


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
