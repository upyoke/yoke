"""Which shell ``yoke setup`` picks, and the usage rules around agent mode."""

from __future__ import annotations

from yoke_contracts.testing.real_home_isolation import set_home

import io
import json
import sys
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    isolate_agent_setup,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.commands.adapters import onboard_hosted_authorization as hosted_auth
from yoke_cli.commands.adapters import onboard_interactive
from yoke_cli.config import (
    onboard_apply_report,
    onboard_machine_setup,
    onboard_wizard,
    setup_agent_answers,
    setup_release_follow,
)
from yoke_contracts import onboard_destinations as onboard_destinations
from yoke_cli.config.onboard_wizard_path import PathFlow

pytest.importorskip("textual")


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    set_home(monkeypatch, str(tmp_path / "home"))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(onboard_machine_setup, "prepare", lambda *_: None)
    # These gates exercise shell selection and questions, not the runner's PATH.
    monkeypatch.setattr(
        PathFlow, "_check_install", lambda _: ({"login_verified": True}, "")
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))


def _terminal(monkeypatch, attached: bool) -> None:
    monkeypatch.setattr(onboard_wizard, "is_interactive", lambda *_: attached)


def _setup(capsys, *args: str) -> tuple[int, list[dict], str]:
    code = yoke_operations_cli.main(["setup", *args])
    captured = capsys.readouterr()
    lines = [json.loads(line) for line in captured.out.splitlines() if line.startswith("{")]
    return code, lines, captured.err


def test_no_terminal_enters_agent_mode_and_asks_one_question(monkeypatch, capsys):
    _terminal(monkeypatch, False)

    code, lines, _ = _setup(capsys)

    assert code == 0
    assert [line["state"] for line in lines] == ["question"]
    assert lines[0]["key"] == "project.mode"
    assert setup_agent_answers.store_path().exists()


def test_agent_flag_forces_agent_mode_in_a_terminal(monkeypatch, capsys):
    _terminal(monkeypatch, True)
    monkeypatch.setattr(
        onboard_interactive.onboard_wizard,
        "run_wizard",
        lambda *_a, **_k: pytest.fail("--agent must not open the wizard"),
    )

    code, lines, _ = _setup(capsys, "--agent")

    assert code == 0
    assert lines[-1]["setup"] == "agent"
    assert lines[-1]["state"] == "question"


def test_agent_release_follow_resumes_same_report_on_review_confirmation(
    tmp_path, monkeypatch, capsys
):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    agent = AgentDriver(capsys)
    agent.walk(MACHINE_ONLY_ANSWERS)
    resumed_args = []

    def follow_once(kwargs):
        if kwargs.get("resume_run_id"):
            return
        report = onboard_apply_report.ApplyReportWriter.start({}, kwargs)
        followed = setup_release_follow.ReleaseFollowed(
            report.payload["run_id"], "old", "new", "/bin/yoke"
        )
        report.payload["cli_followed_release"] = followed.record()
        report.write()
        raise followed

    def run_on_release(_launcher, args, _marker):
        resumed_args.extend(args)
        return yoke_operations_cli.main(args)

    fake.effects = follow_once
    monkeypatch.setattr(setup_release_follow, "run_on_release", run_on_release)

    code, lines = agent("review.confirm=apply")

    assert code == 0, lines
    assert (lines[-1]["state"], lines[-1]["key"]) == ("question", "review.confirm")
    run_id = resumed_args[2]
    assert resumed_args == ["setup", "--resume", run_id, "--agent"]
    assert len(fake.applied) == 1

    code, lines = agent("review.confirm=apply")

    assert (code, lines[-1]["state"]) == (0, "done"), lines
    assert len(fake.applied) == 2
    resumed = fake.applied[-1]
    assert resumed["resume_run_id"] == run_id
    assert resumed["resume_payload"]["cli_followed_release"] == {"from": "old", "to": "new"}
    assert resumed["project_mode"] == "machine-only"
    assert resumed["admin_name"] == "Test Person"
    assert not setup_agent_answers.store_path().exists()


def test_tui_without_a_terminal_refuses(monkeypatch, capsys):
    _terminal(monkeypatch, False)

    code, lines, _ = _setup(capsys, "--tui")

    assert code == 2
    assert lines[-1]["state"] == "refused"
    assert lines[-1]["reason"] == "setup_tui_requires_terminal"
    assert "yoke setup --agent" in lines[-1]["recovery"]


def test_tui_opens_the_wizard_even_when_flags_answer_everything(monkeypatch, capsys):
    _terminal(monkeypatch, True)
    monkeypatch.setattr(onboard_interactive, "require_foreground_terminal", lambda: None)
    opened = []

    def wizard(defaults, *, apply_report):
        opened.append(defaults.destination)
        return onboard_wizard.WizardRunResult(exit_code=0)

    monkeypatch.setattr(onboard_interactive.onboard_wizard, "run_wizard", wizard)
    monkeypatch.setattr(onboard_interactive, "finish_pending_source_install", lambda *_: None)

    code, _, _ = _setup(capsys, "--tui", "--local", "--project-mode", "machine-only")

    assert code == 0
    assert opened == [onboard_destinations.DESTINATION_LOCAL]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--agent", "--json"], "--agent cannot be combined with --json"),
        (["--agent", "--non-interactive"], "--agent cannot be combined with --non-interactive"),
        (["--agent", "--use-different-folder", "run-1"], "--use-different-folder"),
        (["--agent", "token-value"], "TOKEN, --token-file or --token-stdin"),
        (["--agent", "--token-file", "/tmp/t"], "TOKEN, --token-file or --token-stdin"),
        (["--answer", "a=b", "--non-interactive"], "belong to `yoke setup --agent`"),
        (["--tui", "--json"], "--tui cannot be combined"),
        (["--agent", "--answer", "no-equals"], "--answer takes KEY=VALUE"),
        (["--agent", "--answer", "a=1", "--answer", "a=2"], "--answer a was given twice"),
        (["--agent", "--discard", "--answer", "a=b"], "--discard cannot be combined"),
    ],
)
def test_agent_usage_errors_exit_two_with_the_named_clash(monkeypatch, capsys, args, message):
    _terminal(monkeypatch, False)

    code, lines, err = _setup(capsys, *args)

    assert code == 2
    assert lines == []
    assert message in err
    assert "secret" not in err
    assert "token-value" not in err


def test_agent_and_tui_together_is_a_usage_error(monkeypatch, capsys):
    _terminal(monkeypatch, False)

    code, lines, err = _setup(capsys, "--agent", "--tui")

    assert code == 2
    assert lines == []
    assert "not allowed with argument" in err


def test_a_token_without_a_terminal_names_both_routes(monkeypatch, capsys):
    _terminal(monkeypatch, False)

    code, _, err = _setup(capsys, "--token-file", "/tmp/token")

    assert code == 2
    assert "--non-interactive" in err
    assert "yoke setup --agent" in err


def test_missing_flags_on_the_flag_path_name_agent_mode(monkeypatch, capsys):
    _terminal(monkeypatch, False)

    code, _, err = _setup(capsys, "--non-interactive")

    assert code == 2
    assert "missing required onboarding flags" in err
    assert "--api-url" in err
    assert "yoke setup --agent" in err


def test_cloud_browser_approval_recovery_names_agent_mode():
    hosted = onboard_destinations.DESTINATION_HOSTED
    for message in (
        hosted_auth.usage_error(hosted, False, False, False),
        hosted_auth.usage_error(hosted, True, False, False),
    ):
        assert "yoke setup --agent" in message
        assert "rerun setup" not in message


def test_discard_deletes_the_in_progress_setup(monkeypatch, capsys):
    _terminal(monkeypatch, False)
    _setup(capsys)
    assert setup_agent_answers.store_path().exists()

    code, lines, _ = _setup(capsys, "--agent", "--discard")
    again, repeat, _ = _setup(capsys, "--agent", "--discard")

    assert (code, lines[-1]["state"], lines[-1]["discarded"]) == (0, "done", True)
    assert not setup_agent_answers.store_path().exists()
    assert (again, repeat[-1]["discarded"]) == (0, False)


def test_discard_removes_a_store_too_damaged_to_load(monkeypatch, capsys):
    _terminal(monkeypatch, False)
    path = setup_agent_answers.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    path.chmod(0o600)

    code, lines, _ = _setup(capsys, "--agent")
    assert (code, lines[-1]["reason"]) == (2, "setup_agent_store_unreadable")

    code, lines, _ = _setup(capsys, "--agent", "--discard")
    assert (code, lines[-1]["discarded"]) == (0, True)
