"""Resuming an Apply that stopped at its agent-rules stage.

The install that motivated this stopped at ``project-install-agent-rules``
with everything before it already written, and offered a resume. What a
resume owes that operator is the rest of the run without a second copy of
what already landed: the steps that finished stay finished, the one that
failed is attempted again, and the ones after it run for the first time.

None of it may quietly acquire a session either. Onboarding happens
before any harness has run on the machine, so a resume that only works
because something injected a session id would pass here and fail on the
machine it was written for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.config import onboard_apply_report
from yoke_contracts.session_identity import AMBIENT_ENV_VARS


APPLY_STEPS = [
    {"action": "create-or-validate-dir", "target": "/tmp/home"},
    {"action": "set-active-env", "target": "local"},
    {"action": "store-token-reference", "target": "/tmp/token"},
    {"action": "project-clone", "target": "/tmp/buzz"},
    {"action": "project-create", "target": "buzz"},
    {"action": "project-checkout-register", "target": "/tmp/buzz"},
    {"action": "project-install-scaffold", "target": ""},
    {"action": "project-install-agent-rules", "target": ""},
    {"action": "project-install-tool-permissions", "target": ""},
    {"action": "project-install-harness-hooks", "target": ""},
    {"action": "project-install-git-hooks", "target": ""},
]

FAILED_AT = "project-install-agent-rules"
BEFORE_FAILURE = [
    step["action"] for step in APPLY_STEPS
][: [s["action"] for s in APPLY_STEPS].index(FAILED_AT)]
AFTER_FAILURE = [
    step["action"] for step in APPLY_STEPS
][[s["action"] for s in APPLY_STEPS].index(FAILED_AT) + 1:]


def _preview() -> dict:
    return {
        "operation": "onboard",
        "mode": "guided",
        "project_mode": "local-checkout",
        "config_path": "/tmp/home/config.json",
        "plan": {"project": {"name": "buzz"}, "steps": list(APPLY_STEPS)},
    }


@pytest.fixture
def no_session(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _partial_run() -> dict:
    """A run that wrote everything up to the agent-rules stage, then failed."""
    writer = onboard_apply_report.ApplyReportWriter.start(_preview(), {})
    for step in APPLY_STEPS:
        if step["action"] not in BEFORE_FAILURE:
            break
        writer.step_started(step["action"], step["target"])
        writer.step_done(step["action"], step["target"])
    writer.step_started(FAILED_AT, "")
    writer.fail(RuntimeError("project_structure.patch.apply failed"))
    return json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))


def _statuses(payload: dict) -> dict[str, str]:
    return {step["action"]: step["status"] for step in payload["steps"]}


def test_the_partial_run_records_where_it_stopped(no_session):
    payload = _partial_run()
    assert payload["final_status"] == "failed"
    assert _statuses(payload)[FAILED_AT] == "failed"
    assert payload["resume_command"].endswith(payload["run_id"])


def test_resume_keeps_the_completed_steps_and_reruns_nothing_before_the_stop(
    no_session,
):
    previous = _partial_run()
    resumed = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )
    payload = json.loads(
        Path(resumed.summary()["path"]).read_text(encoding="utf-8")
    )
    statuses = _statuses(payload)
    assert payload["run_id"] == previous["run_id"]
    for action in BEFORE_FAILURE:
        assert statuses[action] == "done", action


def test_resume_reopens_the_failed_step_and_the_ones_after_it(no_session):
    previous = _partial_run()
    resumed = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )
    statuses = _statuses(
        json.loads(Path(resumed.summary()["path"]).read_text(encoding="utf-8"))
    )
    assert statuses[FAILED_AT] == "pending"
    for action in AFTER_FAILURE:
        assert statuses[action] == "pending", action


def test_the_resumed_run_completes_every_remaining_step(no_session):
    previous = _partial_run()
    resumed = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )
    for action in [FAILED_AT, *AFTER_FAILURE]:
        resumed.step_started(action, "")
        resumed.step_done(action, "")
    resumed.finish()
    payload = json.loads(
        Path(resumed.summary()["path"]).read_text(encoding="utf-8")
    )
    assert payload["final_status"] == "done"
    assert set(_statuses(payload).values()) == {"done"}
    assert payload["run_id"] == previous["run_id"]


def test_the_resume_never_acquires_a_session_of_its_own(no_session, monkeypatch):
    """No hidden injection: the whole resume runs with the env still empty."""
    previous = _partial_run()
    onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )
    import os

    assert [name for name in AMBIENT_ENV_VARS if os.environ.get(name)] == []


def test_one_run_id_means_one_report_file(no_session):
    """A second copy of the run is exactly the duplication resume must avoid."""
    previous = _partial_run()
    onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )
    reports_dir = onboard_apply_report.run_report_path(
        previous["run_id"]
    ).parent
    reports = sorted(reports_dir.glob("*.json"))
    assert [path.stem for path in reports] == [previous["run_id"]]
