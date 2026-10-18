"""Setup command replies consume the shared client summary once."""

import json
from io import StringIO
from types import SimpleNamespace

import pytest
from yoke_cli.commands.adapters import install, config_write_project, onboard_checklist
from yoke_cli.config import setup_facts_summary, setup_agent_answering

ACTION = {
    "row_id": "strategy-setup",
    "title": "Strategy",
    "status": "unknown",
    "reason": "setup_required",
    "command": "/yoke onboard",
    "home": ".yoke/docs/start/terminal-onboarding.md",
}
SUMMARY = {
    "lines": ["Setup: unknown strategy-setup", "Next: /yoke onboard"],
    "next_action": ACTION,
}


@pytest.mark.parametrize("operation", ["install", "refresh"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_install_refresh_summary_is_structured_or_human(
    monkeypatch, capsys, operation, json_mode
):
    calls = []

    def read(*args, **kwargs):
        calls.append((args, kwargs))
        return SUMMARY

    monkeypatch.setattr(setup_facts_summary, "read_project", read)
    assert (
        install._run(
            lambda: {"operation": operation, "repo_root": "/external", "project_id": 9},
            json_mode=json_mode,
            config_path="/machine.json",
        )
        == 0
    )
    out = capsys.readouterr().out
    if json_mode:
        assert json.loads(out)["next_action"] == ACTION
    else:
        assert out.endswith("Setup: unknown strategy-setup\nNext: /yoke onboard\n")
    assert len(calls) == 1 and calls[0][1]["config_path"] == "/machine.json"


@pytest.mark.parametrize("json_mode", [False, True])
def test_register_summary_preserves_machine_config_selection(
    monkeypatch, capsys, json_mode
):
    monkeypatch.setattr(
        config_write_project.writer,
        "register_project",
        lambda *a, **kw: {"project_id": 9},
    )
    monkeypatch.setattr(setup_facts_summary, "read_project", lambda *a, **kw: SUMMARY)
    args = ["/external", "--project-id", "9", "--config", "/machine.json"]
    assert (
        config_write_project.project_register(args + (["--json"] if json_mode else []))
        == 0
    )
    out = capsys.readouterr().out
    if json_mode:
        assert json.loads(out)["next_action"] == ACTION
    else:
        assert "Next: /yoke onboard" in out


def test_checklist_init_uses_response_next_action():
    stream = StringIO()
    onboard_checklist._render_init_human(
        SimpleNamespace(
            result={
                "run": {
                    "rows": [{"row_id": "strategy-setup", "status": "unknown"}],
                    "next_action": ACTION,
                }
            }
        ),
        stream,
        StringIO(),
    )
    assert "Next: /yoke onboard" in stream.getvalue()
    assert "Next:\n  - yoke setup" not in stream.getvalue()


def test_setup_done_keeps_readiness_before_shared_project_action(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_facts_summary, "read_project", lambda *a, **kw: SUMMARY)
    flow = setup_agent_answering.AnswerFlow()
    flow.result = SimpleNamespace(path_repair=None, project_checkout=str(tmp_path))
    flow.report_path = None
    result = flow._done_fields()
    assert "doctor run --session" in result["next"][0]
    assert "/yoke onboard" in result["next"][1]
    assert result["next_action"] == ACTION
