"""The agent-setup answer store, answer checking and the named refusals."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    git_checkout,
    isolate_agent_setup,
)
from yoke_cli.config import setup_agent_answers
from yoke_contracts import owner_private_path

pytest.importorskip("textual")


@pytest.fixture
def agent(tmp_path: Path, monkeypatch, capsys):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    return AgentDriver(capsys), fake


def _store_bytes() -> bytes:
    return setup_agent_answers.store_path().read_bytes()


def _refused(result, reason: str, key: str) -> dict:
    code, lines = result
    assert code == 2, lines
    line = lines[-1]
    assert (line["state"], line["reason"], line["key"]) == ("refused", reason, key)
    assert line["recovery"]
    assert line["question"]
    assert line["answer_command"]
    return line


def test_store_is_private_and_keyed_by_question(agent):
    drive, _ = agent

    drive.walk(MACHINE_ONLY_ANSWERS[:4])

    path = setup_agent_answers.store_path()
    assert owner_private_path.is_owner_private_file(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["waiting_key"] == "github.machine"
    assert record["answers"] == {
        "project.mode": "machine-only",
        "connect.destination": "local",
        "connect.local_universe": "fresh",
        "connect.admin_name": "Test Person",
    }


def test_an_answer_for_another_question_is_not_current(agent):
    drive, _ = agent
    drive.walk(MACHINE_ONLY_ANSWERS[:4])
    before = _store_bytes()

    _refused(
        drive("project.mode=machine-only"), "setup_answer_not_current", "github.machine"
    )

    assert _store_bytes() == before


def test_a_value_outside_the_choices_is_not_allowed(agent):
    drive, _ = agent
    drive.walk(MACHINE_ONLY_ANSWERS[:4])
    before = _store_bytes()

    line = _refused(
        drive("github.machine=maybe"), "setup_answer_not_allowed", "github.machine"
    )

    assert {row["value"] for row in line["answers"]} >= {"connect", "skip"}
    assert _store_bytes() == before


def test_an_input_runs_the_screens_own_validation(agent, tmp_path: Path):
    drive, _ = agent
    drive.walk(("project.mode=local-checkout", *MACHINE_ONLY_ANSWERS[1:]))
    plain_file = tmp_path / "notes.txt"
    plain_file.write_text("not a folder", encoding="utf-8")
    before = _store_bytes()

    line = _refused(
        drive(f"project.folder={plain_file}"),
        "setup_answer_invalid",
        "project.folder",
    )

    assert "is a file, not a folder" in line["recovery"]
    assert _store_bytes() == before


def test_an_invalid_form_field_names_the_field(agent, tmp_path: Path):
    drive, _ = agent
    checkout = git_checkout(tmp_path / "demo")
    drive.walk(
        (
            "project.mode=local-checkout",
            *MACHINE_ONLY_ANSWERS[1:],
            f"project.folder={checkout}",
        )
    )
    before = _store_bytes()

    line = _refused(
        drive("project.details.slug=Not A Slug!", "project.details=continue"),
        "setup_answer_invalid",
        "project.details",
    )

    assert line["recovery"].startswith("project.details.slug:")
    assert _store_bytes() == before


SERVER_FORM_ROUTE = (
    "project.mode=machine-only",
    "connect.destination=server",
    "connect.team_server_url=https://yoke.example.invalid",
    "connect.yoke_verify_error=token",
)


@pytest.fixture
def no_company_sign_in(monkeypatch):
    from yoke_cli.config import hosted_machine_authorization

    def unavailable(*_a, **_k):
        raise RuntimeError("machine_sign_in_unavailable: this server uses API tokens")

    monkeypatch.setattr(hosted_machine_authorization, "start", unavailable)


def test_a_secret_input_never_takes_an_answer(agent, no_company_sign_in):
    drive, _ = agent
    code, lines = drive.walk(SERVER_FORM_ROUTE)
    form = lines[-1]
    assert form["key"] == "connect.server"
    assert form["secret"] is True
    assert "choose file" in form["guidance"]
    before = _store_bytes()

    _refused(
        drive("connect.server.credential=s3cret"),
        "setup_secret_answer_refused",
        "connect.server",
    )

    assert _store_bytes() == before
    assert b"s3cret" not in before


def test_the_token_file_route_survives_a_fresh_invocation(
    agent, no_company_sign_in, monkeypatch, tmp_path
):
    from yoke_cli.config import onboard_wizard_flow_connect

    drive, _ = agent
    drive.walk(SERVER_FORM_ROUTE)
    code, lines = drive("connect.server=file")
    assert (code, lines[-1]["key"], lines[-1]["secret"]) == (0, "connect.server", False)
    assert _last_key(drive()) == "connect.server"
    token_file = tmp_path / "team.token"
    token_file.write_text("team-token-value\n", encoding="utf-8")
    token_file.chmod(0o600)
    verified = {
        "ok": True,
        "actor": {"label": "T"},
        "orgs": [{"name": "Acme"}],
        "projects": [{"slug": "demo", "public_item_prefix": "DMO"}],
    }
    monkeypatch.setattr(
        onboard_wizard_flow_connect, "verify_yoke_token", lambda *_a: verified
    )

    code, lines = drive(f"connect.server.credential={token_file}")

    assert (code, lines[-1]["key"]) == (0, "github.machine"), lines
    assert b"team-token-value" not in _store_bytes()


def _last_key(result) -> str:
    return result[1][-1]["key"]


def test_changed_presets_refuse_and_keep_the_stored_ones(agent):
    drive, _ = agent
    drive.walk(MACHINE_ONLY_ANSWERS[:3])
    before = _store_bytes()

    code, lines = drive(flags=("--yes",))
    line = lines[-1]
    assert (code, line["reason"], line["key"]) == (
        2, "setup_agent_flags_changed", "connect.admin_name"
    )

    assert "--discard" in line["recovery"]
    assert _store_bytes() == before


def test_flags_replace_the_presets_of_a_run_with_no_answers(agent):
    facts = {"machine": {"step": "done"}}
    store = setup_agent_answers.AnswerStore(
        {"presets": {"post_install": True}, "waiting_key": "project.mode",
         "facts": facts},
        existed=True,
    )

    assert store.apply_presets({"api_url": "https://yoke.example"}) is None
    assert store.presets == {"api_url": "https://yoke.example"}
    assert store.facts == facts


def test_flags_still_refuse_once_a_question_is_answered(agent):
    store = setup_agent_answers.AnswerStore(
        {"presets": {"post_install": True}, "waiting_key": "connect.destination",
         "answers": {"project.mode": "machine-only"}},
        existed=True,
    )

    refusal = store.apply_presets({"api_url": "https://yoke.example"})
    assert refusal is not None and refusal[0] == "setup_agent_flags_changed"
    assert store.presets == {"post_install": True}


def test_changed_presets_stop_before_machine_setup(agent, monkeypatch):
    from unittest.mock import Mock

    from runtime.api.cli.setup_agent_approvals_test_support import _pending
    from yoke_cli.commands.adapters import onboard_agent
    from yoke_cli.config import hosted_machine_authorization

    drive, _ = agent
    start = Mock(return_value=_pending("FIRST"))
    monkeypatch.setattr(hosted_machine_authorization, "start", start)
    drive.walk(("project.mode=machine-only", "connect.destination=hosted"))
    start.reset_mock()
    before = _store_bytes()
    assert json.loads(before)["pending_approval"]
    prepare = Mock(side_effect=AssertionError("refused setup must stop before prepare"))
    monkeypatch.setattr(onboard_agent.onboard_resume, "prepare_run", prepare)
    monkeypatch.setattr(onboard_agent.onboard_machine_setup, "prepare", prepare)
    monkeypatch.setattr(onboard_agent, "_agent_setup", prepare)

    code, lines = drive(flags=("--yes",))

    assert code == 2
    assert len(lines) == 1
    assert lines[0]["reason"] == "setup_agent_flags_changed"
    assert lines[0]["key"] == json.loads(before)["waiting_key"]
    assert "https://" not in json.dumps(lines) + drive.stderr
    start.assert_not_called()
    prepare.assert_not_called()
    assert _store_bytes() == before


def test_repeating_the_stored_presets_is_allowed(agent):
    drive, fake = agent
    drive(flags=("--yes",))

    code, lines = drive(MACHINE_ONLY_ANSWERS[0], flags=("--yes",))

    assert (code, lines[-1]["key"]) == (0, "connect.destination")


def test_a_second_invocation_refuses_while_one_runs(agent):
    drive, _ = agent
    drive()
    held = setup_agent_answers.open_store()
    try:
        code, lines = drive()
    finally:
        held.release()

    assert (code, lines[-1]["state"], lines[-1]["reason"]) == (
        2,
        "refused",
        "setup_agent_busy",
    )


@pytest.mark.posix_only(reason="chmod exposes the answer file to another POSIX user")
def test_a_store_with_loose_permissions_is_refused(agent):
    drive, _ = agent
    drive()
    os.chmod(setup_agent_answers.store_path(), 0o644)

    code, lines = drive()

    assert (code, lines[-1]["reason"]) == (2, "setup_agent_store_unreadable")
    assert "yoke setup --agent --discard" in lines[-1]["recovery"]


@pytest.mark.windows
@pytest.mark.windows_only(reason="real Windows file security")
def test_a_store_with_loose_acl_is_refused(agent):
    drive, _ = agent
    drive()
    path = setup_agent_answers.store_path()
    subprocess.run(
        ["icacls", str(path), "/grant", "*S-1-1-0:(R)"],
        check=True, capture_output=True,
    )
    assert not owner_private_path.is_owner_private_file(path)

    code, lines = drive()

    assert (code, lines[-1]["reason"]) == (2, "setup_agent_store_unreadable")
    assert "yoke setup --agent --discard" in lines[-1]["recovery"]


def test_a_stored_answer_the_screen_now_rejects_is_asked_again(agent):
    drive, _ = agent
    drive.walk(MACHINE_ONLY_ANSWERS[:4])
    path = setup_agent_answers.store_path()
    record = json.loads(path.read_text(encoding="utf-8"))
    record["answers"]["connect.local_universe"] = "retired-choice"
    record["waiting_key"] = None
    path.write_text(json.dumps(record), encoding="utf-8")

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "connect.local_universe")


def test_a_run_fact_is_saved_at_once_and_survives_a_refusal(agent):
    drive, _ = agent
    drive()
    store = setup_agent_answers.open_store()
    try:
        store.keep_facts({"cloned_checkout": "/tmp/demo"})
    finally:
        store.release()

    code, lines = drive("github.machine=skip")

    assert lines[-1]["reason"] == "setup_answer_not_current"
    record = json.loads(setup_agent_answers.store_path().read_text(encoding="utf-8"))
    assert record["facts"] == {"cloned_checkout": "/tmp/demo"}
