"""Tests for HC-board-settings-authority."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_board_settings_authority as mod


def _run(monkeypatch, projects: list[dict]):
    monkeypatch.setattr(
        mod.machine_config,
        "load_config",
        lambda: {"projects": projects},
    )
    records = RecordCollector()
    mod.hc_board_settings_authority(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def test_passes_for_checkout_without_retired_board_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result = _run(monkeypatch, [{"checkout": str(tmp_path), "project_id": 1}])

    assert result.result == "PASS"


def test_fails_for_retired_board_settings_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    board_file = tmp_path / ".yoke" / "board.json"
    board_file.parent.mkdir(parents=True)
    board_file.write_text(
        json.dumps({"dashboard_weather": False}),
        encoding="utf-8",
    )

    result = _run(monkeypatch, [{"checkout": str(tmp_path), "project_id": 1}])

    assert result.result == "FAIL"
    assert "board.json settings remain" in result.detail


def test_fails_for_retired_machine_board_entry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result = _run(monkeypatch, [{
        "checkout": str(tmp_path),
        "project_id": 1,
        "board": {"scope": "all"},
    }])

    assert result.result == "FAIL"
    assert "machine projects[].board present" in result.detail
