"""Agent-mode setup walked end to end through the wizard's own flows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    git_checkout,
    isolate_agent_setup,
)
from yoke_cli.config import (
    github_machine,
    machine_config,
    onboard_apply_resume,
    onboard_wizard,
    setup_agent_answers,
    writer,
    yoke_token_verify,
)
from yoke_cli.config import onboard_wizard_flow_apply as flow_apply

pytest.importorskip("textual")


@pytest.fixture
def agent(tmp_path: Path, monkeypatch, capsys):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    return AgentDriver(capsys), fake


def _last(result):
    code, lines = result
    return code, lines[-1]


def test_machine_only_setup_finishes_with_answers_only(agent):
    drive, fake = agent

    code, line = _last(drive.walk(MACHINE_ONLY_ANSWERS))
    assert (code, line["state"], line["key"]) == (0, "question", "review.confirm")
    assert fake.applied == []

    code, line = _last(drive("review.confirm=apply"))

    assert (code, line["state"]) == (0, "done"), line
    assert line["install_health"] == {
        "ok": True,
        "checks": [{"name": "yoke", "ok": True}],
    }
    assert line["report"]["path"] == "/tmp/report.json"
    assert line["next"]
    assert fake.options == [{"install_health": True}]
    assert fake.applied[0]["project_mode"] == "machine-only"
    assert not setup_agent_answers.store_path().exists()


def test_every_line_is_one_json_object_and_progress_goes_to_stderr(agent):
    drive, _ = agent

    code, lines = drive()

    assert code == 0
    assert len(lines) == 1
    assert lines[0]["answer_command"].endswith(
        "setup --agent --answer project.mode=<value>"
    )
    assert "{" not in drive.stderr


def test_a_fresh_invocation_resumes_at_the_next_question(agent):
    drive, _ = agent
    drive.walk(MACHINE_ONLY_ANSWERS[:4])

    first = _last(drive())
    second = _last(drive())

    assert first == second
    assert first[1]["key"] == "github.machine"


def test_the_first_call_may_answer_the_first_question(agent):
    drive, _ = agent

    code, line = _last(drive("project.mode=machine-only"))

    assert (code, line["key"]) == (0, "connect.destination")


def test_yes_preset_answers_review_and_later_calls_may_omit_it(agent):
    drive, fake = agent
    drive(flags=("--yes",))

    for answer in MACHINE_ONLY_ANSWERS:
        code, line = _last(drive(answer))

    assert (code, line["state"]) == (0, "done"), line
    assert len(fake.applied) == 1


def test_local_checkout_setup_answers_the_details_form_by_field(agent, tmp_path: Path):
    drive, fake = agent
    checkout = git_checkout(tmp_path / "demo")
    answers = (
        "project.mode=local-checkout",
        *MACHINE_ONLY_ANSWERS[1:],
        f"project.folder={checkout}",
    )
    code, line = _last(drive.walk(answers))
    assert line["key"] == "project.details"
    fields = {field["key"]: field["default"] for field in line["fields"]}
    assert fields["project.details.slug"] == "demo"

    code, line = _last(
        drive("project.details.name=Demo App", "project.details=continue")
    )
    assert line["key"] == "project.publish"
    for answer in ("project.publish=keep-local", "hosting.provider=skip"):
        code, line = _last(drive(answer))
    assert line["key"] == "review.confirm"

    code, line = _last(drive("review.confirm=apply"))

    assert (code, line["state"]) == (0, "done"), line
    applied = fake.applied[0]
    assert (applied["project_slug"], applied["project_name"]) == ("demo", "Demo App")
    assert applied["project_checkout"] == str(checkout)
    assert any(str(checkout) in step for step in line["next"])


def test_review_is_never_answered_from_a_stored_answer(agent):
    drive, fake = agent
    drive.walk(MACHINE_ONLY_ANSWERS)
    drive("review.confirm=show-all")

    code, line = _last(drive())

    assert (code, line["key"]) == (0, "review.confirm")
    assert fake.applied == []


TOKEN = "token-never-shown"
VERIFIED = {
    "ok": True,
    "actor": {"label": "Test Person"},
    "orgs": [{"name": "Acme"}],
    "projects": [],
}


def test_saved_github_authorization_skips_the_github_question(agent, monkeypatch):
    drive, _ = agent
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda *_a, **_k: {"authorization": {"status": "authorized"}},
    )
    monkeypatch.setattr(
        github_machine,
        "status",
        lambda **_k: {
            "ok": True,
            "ready": True,
            "configured": True,
            "api_url": "https://api.github.com",
        },
    )

    code, lines = drive.walk(MACHINE_ONLY_ANSWERS[:4])

    assert (code, lines[-1]["key"]) == (0, "github.connected")


def test_saved_yoke_sign_in_is_reused_without_a_browser_step(agent, monkeypatch):
    drive, _ = agent
    writer.set_connection(
        "acme",
        transport="https",
        api_url="https://app.upyoke.com/api/orgs/acme",
        token=TOKEN,
        activate=True,
        path=str(machine_config.config_path(None)),
    )
    monkeypatch.setattr(yoke_token_verify, "verify", lambda *_a, **_k: VERIFIED)

    code, first = drive("project.mode=machine-only")
    assert first[-1]["key"] == "connect.saved_destination"
    code, lines = drive("connect.saved_destination=stored")

    assert (code, [line["state"] for line in lines]) == (0, ["question"])
    assert lines[-1]["key"] == "github.machine"
    assert TOKEN not in json.dumps(first + lines)


@pytest.fixture
def resumable(monkeypatch):
    monkeypatch.setattr(flow_apply, "_can_resume_run", lambda _run: True)
    monkeypatch.setattr(flow_apply, "_apply_report_run_id", lambda _path: "run-1")
    monkeypatch.setattr(
        onboard_apply_resume, "load_payload", lambda _run: {"saved": True}
    )
    monkeypatch.setattr(onboard_apply_resume, "load_snapshot", lambda _run: {})


def test_apply_failure_returns_failed_and_resume_continues_the_run(agent, resumable):
    drive, fake = agent
    drive.walk(MACHINE_ONLY_ANSWERS)
    fake.fail_next = onboard_wizard.WizardApplyError(
        "the relay did not start",
        failed_step="install-session-relay",
        report_path="/tmp/run-1.json",
        resume_command="yoke setup --resume run-1",
    )

    code, line = _last(drive("review.confirm=apply"))
    assert (code, line["state"], line["reason"]) == (1, "failed", "setup_apply_failed")
    assert (line["report_path"], line["key"]) == (
        "/tmp/run-1.json",
        "review.apply_failed",
    )
    assert "resume" in {row["value"] for row in line["answers"]}

    assert _last(drive()) == (code, line)

    code, done = _last(drive("review.apply_failed=resume"))

    assert (code, done["state"]) == (0, "done")
    assert fake.applied[-1]["resume_run_id"] == "run-1"
    assert fake.applied[-1]["resume_payload"] == {"saved": True}
    assert not setup_agent_answers.store_path().exists()


def test_cancel_at_review_ends_and_discards_the_setup(agent):
    drive, fake = agent
    drive.walk(MACHINE_ONLY_ANSWERS)

    code, line = _last(drive("review.confirm=cancel"))

    assert (code, line["state"], line.get("cancelled")) == (0, "done", True), line
    assert fake.applied == []
    assert not setup_agent_answers.store_path().exists()


@pytest.mark.parametrize(
    ("method", "named"),
    [
        ("_goto_finish", "KeyError: 'plan'"),
        ("_build_review_model", "Couldn't build your setup plan."),
    ],
)
def test_an_unexpected_exception_is_a_named_failure_not_a_traceback(
    agent, monkeypatch, method, named
):
    drive, _ = agent
    from yoke_cli.config import onboard_wizard_flow

    def explode(self):
        raise KeyError("plan")

    monkeypatch.setattr(onboard_wizard_flow.WizardFlow, method, explode)
    drive.walk(MACHINE_ONLY_ANSWERS[:-1])

    code, line = _last(drive(MACHINE_ONLY_ANSWERS[-1]))

    assert code == 1
    assert (line["state"], line["reason"]) == ("failed", "setup_step_failed")
    assert named in line["recovery"]
    assert "Traceback" not in drive.stderr
