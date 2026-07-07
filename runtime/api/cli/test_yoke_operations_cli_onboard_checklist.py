from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionCallRequest,
    TargetRef,
)


_CAPTURED_CALLS: list[dict[str, Any]] = []


def _row(
    row_id: str,
    status: str,
    *,
    evidence: Any = "",
    blocker: str = "",
    note: str = "",
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "step": "2",
        "title": "Machine profile",
        "layer": "machine",
        "owner": "yoke onboard",
        "status": status,
        "hint": "Create ~/.yoke and secret storage.",
        "evidence": evidence,
        "blocker": blocker,
        "note": note,
    }


def _run_result(**updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "operation": "onboard.checklist.run",
        "run_id": "run-test",
        "resumed": False,
        "branch": "machine-only",
        "project_id": 7,
        "project_slug": "demo",
        "github_repo": "owner/repo",
        "checkout_path": "/project",
        "status": "blocked",
        "rows": [
            _row(
                "machine-profile",
                "verified",
                evidence={"message": "dispatcher evidence"},
            ),
            _row(
                "machine-github-connection",
                "blocked",
                blocker="missing org grant",
            ),
        ],
        "summary": {
            "status": "blocked",
            "open_rows": ["machine-github-connection"],
            "blocked_rows": ["machine-github-connection"],
        },
    }
    result.update(updates)
    return result


def _init_result(**updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "operation": "onboard.checklist.init",
        "run_id": "run-init",
        "resumed": False,
        "machine_config_path": "/home/config.json",
        "checkout_path": "/checkout",
        "project_id": 7,
        "status": "open",
        "rows": [_row("machine-profile", "needed")],
        "summary": {
            "status": "open",
            "open_rows": ["machine-profile"],
            "blocked_rows": [],
        },
    }
    result.update(updates)
    return result


def _response(kwargs: dict[str, Any], result: dict[str, Any]) -> FunctionCallResponse:
    request = FunctionCallRequest(
        function=kwargs["function_id"],
        actor=kwargs.get("actor") or ActorContext(session_id=""),
        target=kwargs.get("target") or TargetRef(kind="global"),
        payload=kwargs.get("payload") or {},
    )
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result,
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_CALLS.clear()


def _run_capture(
    argv: list[str],
    *,
    result: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    selected = result or _run_result()

    def stub_call_dispatcher(**kwargs: Any) -> FunctionCallResponse:
        _CAPTURED_CALLS.append(kwargs)
        return _response(kwargs, selected)

    with patch("yoke_cli.commands.adapters.onboard_checklist.ensure_handlers_loaded"):
        with patch(
            "yoke_cli.commands.adapters.onboard_checklist.call_dispatcher",
            side_effect=stub_call_dispatcher,
        ):
            rc = yoke_operations_cli.main(argv)
    return rc, "", ""


def test_onboard_checklist_help_exits_cleanly(capsys) -> None:
    rc = yoke_operations_cli.main(["onboard", "checklist", "--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "yoke onboard checklist" in out
    assert "--row-status" in out


def test_onboard_checklist_init_dispatches_and_json_is_response_driven(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine_config = tmp_path / "home" / "config.json"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    result = _init_result(
        machine_config_path=str(machine_config),
        checkout_path=str(checkout),
    )

    rc, _out, _err = _run_capture(
        [
            "onboard",
            "checklist",
            "init",
            "--config",
            str(machine_config),
            "--checkout",
            str(checkout),
            "--project-id",
            "7",
            "--json",
        ],
        result=result,
    )

    assert rc == 0
    call = _CAPTURED_CALLS[-1]
    assert call["function_id"] == "onboard.checklist.init"
    assert call["target"].kind == "global"
    assert call["target"].project_id == "7"
    assert call["payload"] == {
        "machine_config_path": str(machine_config),
        "checkout_path": str(checkout),
        "project_id": 7,
    }
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["success"] is True
    assert envelope["function"] == "onboard.checklist.init"
    assert envelope["result"]["operation"] == "onboard.checklist.init"
    assert envelope["result"]["machine_config_path"] == str(machine_config)


def test_onboard_checklist_run_dispatches_payload_and_renders_response_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    result = _run_result(checkout_path=str(project))

    rc, _out, _err = _run_capture(
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
    call = _CAPTURED_CALLS[-1]
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

    rc, _out, _err = _run_capture(
        [
            "onboard",
            "checklist",
            "--run-id",
            "run-test",
            "--project-root",
            str(project),
            "--no-view",
            "--json",
        ]
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
    assert _CAPTURED_CALLS == []
