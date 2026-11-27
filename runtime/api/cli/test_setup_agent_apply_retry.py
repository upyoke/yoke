"""A failed Apply's printed answer retries the same persisted run (YOK-5780).

Apply had created the hosted project and its item prefix before it failed. The
failure question's ``answer_command`` names that run with ``--resume``, so the
retry reopens it at Review instead of replaying Project details, where the
prefix the first pass took would be refused and a new one proposed.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import (
    onboard_apply_report,
    onboard_preflight,
    onboard_project_create_permission,
    onboard_project_prefixes,
    onboard_wizard,
    writer,
    yoke_token_verify,
)
from yoke_contracts.machine_config import reader as machine_config

pytest.importorskip("textual")

_REAL_PREFLIGHT = onboard_preflight.preflight
API_URL = "https://app.upyoke.com/api/orgs/acme"
SLUG = "qa-retry"
PREFIX = "QARETR"


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch, capsys):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(onboard_preflight, "preflight", _REAL_PREFLIGHT)
    writer.set_connection(
        "acme",
        transport="https",
        api_url=API_URL,
        token="token-never-shown",
        activate=True,
        path=str(machine_config.config_path(None)),
    )
    monkeypatch.setattr(
        yoke_token_verify,
        "verify",
        lambda *_a, **_k: {"ok": True, "actor": {"label": "Testy"}, "orgs": [],
                           "projects": [{"slug": "yoke"}]},
    )
    monkeypatch.setattr(
        onboard_project_create_permission,
        "call_function",
        lambda **_k: {"success": True, "result": {"project_create_orgs": [
            {"slug": "acme", "name": "Acme", "default": True}]}},
    )
    holders: dict[str, str] = {}
    monkeypatch.setattr(
        onboard_project_prefixes, "read_holders", lambda *_a: dict(holders)
    )
    runs: list[str] = []

    def effects(kwargs: dict) -> None:
        # What a real Apply leaves before it fails: its durable report, and
        # the hosted project now holding the reviewed prefix.
        report = onboard_apply_report.ApplyReportWriter.start(
            {"plan": {"steps": []}}, kwargs
        )
        runs.append(report.payload["run_id"])
        holders[str(kwargs["project_public_item_prefix"])] = f"project {SLUG!r} (id 42)"
        if fake.fail_next is not None:
            fake.fail_next = onboard_wizard.WizardApplyError(
                "the relay did not start",
                failed_step="install-session-relay",
                report_path=str(report.path),
                resume_command=report.payload["resume_command"],
            )

    fake.effects = effects
    return AgentDriver(capsys), fake, runs, tmp_path


def _fail_apply(drive: AgentDriver, fake, tmp_path: Path) -> dict:
    folder = tmp_path / "code" / SLUG
    drive.walk(
        (
            "project.mode=create-repo",
            "connect.saved_destination=stored",
            "github.machine=skip",
            f"project.folder={folder}",
        )
    )
    code, lines = drive(f"project.details.prefix={PREFIX}", "project.details=continue")
    assert (code, lines[-1]["key"]) == (0, "hosting.provider"), lines[-1]
    code, lines = drive("hosting.provider=skip")
    assert lines[-1]["key"] == "review.confirm", lines[-1]
    fake.fail_next = RuntimeError("replaced by the report-backed failure")
    code, lines = drive("review.confirm=apply")
    assert (code, lines[-1]["reason"]) == (1, "setup_apply_failed"), lines[-1]
    return lines[-1]


def _run_printed(drive: AgentDriver, line: dict, value: str) -> tuple[int, list]:
    """Run the line's answer_command exactly as printed, with ``value``."""
    argv = shlex.split(line["answer_command"].replace("<value>", value))
    assert Path(argv[0]).name == "yoke", argv
    code = yoke_operations_cli.main(argv[1:])
    out = drive._capsys.readouterr().out
    return code, [json.loads(row) for row in out.splitlines() if row]


@pytest.mark.parametrize("value", ["retry", "resume"])
def test_printed_failed_apply_answer_continues_the_same_run(hosted, value):
    drive, fake, runs, tmp_path = hosted
    failed = _fail_apply(drive, fake, tmp_path)
    run_id = runs[-1]
    assert f"--resume {run_id} " in failed["answer_command"], failed
    assert value in {row["value"] for row in failed["answers"]}

    code, lines = _run_printed(drive, failed, value)

    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    assert all(line.get("key") != "project.details" for line in lines), lines
    assert runs == [run_id, run_id]
    assert fake.applied[-1]["resume_run_id"] == run_id
    assert fake.applied[-1]["project_public_item_prefix"] == PREFIX


def test_printed_answer_refused_at_the_failure_keeps_the_run(hosted):
    drive, fake, runs, tmp_path = hosted
    failed = _fail_apply(drive, fake, tmp_path)

    code, lines = _run_printed(drive, failed, "nonsense")

    assert (code, lines[-1]["reason"]) == (2, "setup_answer_not_allowed"), lines[-1]
    assert lines[-1]["key"] == "review.apply_failed"
    assert f"--resume {runs[-1]} " in lines[-1]["answer_command"]
    code, lines = _run_printed(drive, lines[-1], "retry")
    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    assert runs == [runs[0], runs[0]]


def test_printed_exit_answer_leaves_the_report(hosted):
    drive, fake, runs, tmp_path = hosted
    failed = _fail_apply(drive, fake, tmp_path)

    code, lines = _run_printed(drive, failed, "exit")

    assert (code, lines[-1].get("cancelled")) == (0, True), lines[-1]
    assert onboard_apply_report.run_report_path(runs[-1]).is_file()
    assert len(fake.applied) == 1


def test_printed_back_answer_reaches_review_of_the_same_run(hosted):
    drive, fake, runs, tmp_path = hosted
    failed = _fail_apply(drive, fake, tmp_path)

    code, lines = _run_printed(drive, failed, "back")

    assert (code, lines[-1]["key"]) == (0, "review.confirm"), lines[-1]
    code, lines = _run_printed(drive, lines[-1], "apply")
    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    assert fake.applied[-1]["project_public_item_prefix"] == PREFIX


def test_failure_without_a_report_keeps_the_plain_answer(hosted):
    drive, fake, _runs, tmp_path = hosted
    fake.effects = None
    folder = tmp_path / "code" / SLUG
    drive.walk(
        (
            "project.mode=create-repo",
            "connect.saved_destination=stored",
            "github.machine=skip",
            f"project.folder={folder}",
        )
    )
    drive.walk(("project.details=continue", "hosting.provider=skip"))
    fake.fail_next = onboard_wizard.WizardApplyError("network down")
    code, lines = drive("review.confirm=apply")
    assert (code, lines[-1]["key"]) == (1, "review.apply_failed"), lines[-1]
    assert "--resume" not in lines[-1]["answer_command"]

    code, lines = _run_printed(drive, lines[-1], "retry")

    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    assert fake.applied[-1].get("resume_run_id") is None
