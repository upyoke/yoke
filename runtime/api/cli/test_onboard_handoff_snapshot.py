"""The setup handoff row follows the snapshot sync, and its repair clears it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import project_snapshot
from yoke_cli.config import onboard_handoff_snapshot
from yoke_cli.config import project_onboard_support
from yoke_cli.config.project_onboard_support import ProjectDispatchError
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.onboard_checklist import (
    SETUP_HANDOFF_ROW_ID,
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
)


def _run(status: str) -> dict:
    return {
        "run": {
            "run_id": "run-1",
            "rows": [
                {"row_id": "package-install", "status": "verified"},
                {"row_id": SETUP_HANDOFF_ROW_ID, "status": status},
            ],
        }
    }


def _fake_dispatch(monkeypatch: pytest.MonkeyPatch, run: dict) -> list[tuple]:
    calls: list[tuple] = []

    def dispatch(function_id, payload, config_path):
        calls.append((function_id, dict(payload)))
        return run if function_id == "onboard.checklist.get" else {}

    monkeypatch.setattr(project_onboard_support, "dispatch", dispatch)
    return calls


def test_failed_sync_blocks_the_row_with_its_repair() -> None:
    status, evidence, blocker = onboard_handoff_snapshot.row_update(
        {"status": "failed", "repair_command": "yoke project snapshot sync --project 25"}
    )

    assert status == STATUS_BLOCKED
    assert evidence["snapshot_sync"]["status"] == "failed"
    assert blocker == "Run `yoke project snapshot sync --project 25` before path-claim flows."


def test_successful_sync_configures_the_row() -> None:
    status, _evidence, blocker = onboard_handoff_snapshot.row_update({"status": "ok"})

    assert (status, blocker) == (STATUS_CONFIGURED, None)


def test_repaired_sync_clears_a_blocked_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_dispatch(monkeypatch, _run(STATUS_BLOCKED))

    assert onboard_handoff_snapshot.clear_blocked_row("25") is True

    function_id, payload = calls[-1]
    assert function_id == "onboard.checklist.run"
    assert payload["run_id"] == "run-1"
    assert payload["row_status"] == {SETUP_HANDOFF_ROW_ID: STATUS_CONFIGURED}
    assert payload["blocker"] == {SETUP_HANDOFF_ROW_ID: None}
    assert f"{SETUP_HANDOFF_ROW_ID} configured" in capsys.readouterr().err


def test_unblocked_row_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_dispatch(monkeypatch, _run(STATUS_CONFIGURED))

    assert onboard_handoff_snapshot.clear_blocked_row("25") is False
    assert [call[0] for call in calls] == ["onboard.checklist.get"]


def test_clear_failure_is_named_with_its_recovery(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(function_id, payload, config_path):
        raise ProjectDispatchError(function_id, "forbidden", "not allowed")

    monkeypatch.setattr(project_onboard_support, "dispatch", refuse)

    assert onboard_handoff_snapshot.clear_blocked_row("25") is False
    err = capsys.readouterr().err
    assert "setup_handoff_row_not_cleared" in err
    assert "yoke project snapshot sync --project 25" in err


def test_snapshot_sync_command_clears_the_row_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleared: list[str | None] = []
    monkeypatch.setattr(project_snapshot, "_project_context", lambda _p: "25")
    monkeypatch.setattr(project_snapshot, "plan_sync", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(
        project_snapshot,
        "sync_snapshots",
        lambda **_k: FunctionCallResponse(
            success=True,
            function="project.snapshot.sync",
            version="v1",
            result={"snapshots": [], "warnings": []},
        ),
    )
    monkeypatch.setattr(
        onboard_handoff_snapshot, "clear_blocked_row", lambda project: cleared.append(project)
    )

    assert project_snapshot.project_snapshot_sync([str(tmp_path)]) == 0
    assert cleared == ["25"]
