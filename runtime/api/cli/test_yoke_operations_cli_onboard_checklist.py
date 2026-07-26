from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli
from runtime.api.cli.onboard_checklist_cli_test_helpers import (
    run_cli,
    run_result,
)


def test_onboard_checklist_help_exits_cleanly(capsys) -> None:
    rc = yoke_operations_cli.main(["onboard", "checklist", "--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "yoke onboard checklist" in out
    assert "--row-status" in out


def test_onboard_checklist_run_dispatches_payload_and_renders_response_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    result = run_result(checkout_path=str(project))

    rc, calls = run_cli(
        [
            "onboard",
            "checklist",
            "--run-id",
            "run-test",
            "--branch",
            "machine-only",
            "--project-root",
            str(project),
            "--project-id",
            "7",
            "--project-slug",
            "demo",
            "--github-repo",
            "owner/repo",
            "--row-status",
            "machine-profile=verified",
            "--evidence",
            "machine-profile=config validates",
            "--row-status",
            "machine-github-connection=blocked",
            "--blocker",
            "machine-github-connection=missing org grant",
            "--json",
        ],
        result=result,
    )

    assert rc == 0
    call = calls[-1]
    assert call["function_id"] == "onboard.checklist.run"
    assert call["target"].project_id == "7"
    assert call["payload"] == {
        "run_id": "run-test",
        "branch": "machine-only",
        "checkout_path": str(project),
        "project_root": str(project),
        "project_id": 7,
        "project_slug": "demo",
        "github_repo": "owner/repo",
        "row_status": {
            "machine-profile": "verified",
            "machine-github-connection": "blocked",
        },
        "evidence": {"machine-profile": "config validates"},
        "blocker": {"machine-github-connection": "missing org grant"},
    }

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["rows"][0]["evidence"] == {
        "message": "dispatcher evidence",
    }
    assert payload["result"]["view_path"] == str(
        project / ".yoke" / "onboarding" / "CHECKLIST.md"
    )
    assert not (home / "onboarding-runs" / "run-test.json").exists()
    view = project / ".yoke" / "onboarding" / "CHECKLIST.md"
    assert view.is_file()
    text = view.read_text()
    assert "dispatcher evidence" in text
    assert "config validates" not in text


def test_onboard_checklist_no_view_skips_project_render(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    rc, _calls = run_cli(
        [
            "onboard",
            "checklist",
            "--run-id",
            "run-test",
            "--project-root",
            str(project),
            "--no-view",
            "--json",
        ],
        result=run_result(),
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "view_path" not in payload["result"]
    assert not (project / ".yoke" / "onboarding" / "CHECKLIST.md").exists()


def test_onboard_checklist_rejects_invalid_status(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))

    rc = yoke_operations_cli.main(
        [
            "onboard",
            "checklist",
            "--run-id",
            "bad-status",
            "--row-status",
            "machine-profile=done",
            "--no-view",
        ]
    )

    assert rc == 1
    assert "invalid status" in capsys.readouterr().err
