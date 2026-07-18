"""Apply-time board-art payoff regressions for ``yoke onboard``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_wizard_board_art as art  # noqa: E402
from yoke_cli.config.onboard_wizard import (  # noqa: E402
    WizardApplyError,
    WizardResult,
)
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow  # noqa: E402


def test_rebuild_board_forces_rebuild_and_requires_file(
    tmp_path: Path,
    monkeypatch,
):
    from yoke_cli.board import rebuild as rebuild_mod

    board_path = tmp_path / ".yoke" / "BOARD.md"
    calls: list[dict] = []

    def fake_rebuild(**kwargs):
        calls.append(kwargs)
        board_path.parent.mkdir(parents=True)
        board_path.write_text("board\n", encoding="utf-8")
        return SimpleNamespace(
            board_path=str(board_path),
            exit_code=0,
            message="rebuilt",
        )

    monkeypatch.setattr(rebuild_mod, "rebuild", fake_rebuild)
    monkeypatch.setattr(
        rebuild_mod,
        "resolve_main_repo_root",
        lambda _repo_arg=None: tmp_path,
    )
    assert art.rebuild_board(tmp_path) == board_path
    assert calls == [{
        "repo_arg": str(tmp_path),
        "force": True,
        "emit": False,
    }]


def test_rebuild_board_raises_when_success_does_not_write_file(
    tmp_path: Path,
    monkeypatch,
):
    from yoke_cli.board import rebuild as rebuild_mod

    board_path = tmp_path / ".yoke" / "BOARD.md"
    monkeypatch.setattr(
        rebuild_mod,
        "rebuild",
        lambda **_kwargs: SimpleNamespace(
            board_path=str(board_path),
            exit_code=0,
            message="rebuilt",
        ),
    )
    monkeypatch.setattr(
        rebuild_mod,
        "resolve_main_repo_root",
        lambda _repo_arg=None: tmp_path,
    )

    with pytest.raises(RuntimeError, match="did not write"):
        art.rebuild_board(tmp_path)


def test_rebuild_board_requires_configured_board_path(
    tmp_path: Path,
    monkeypatch,
):
    from yoke_cli.board import rebuild as rebuild_mod

    reported_path = tmp_path / ".yoke" / "OTHER.md"

    def fake_rebuild(**_kwargs):
        reported_path.parent.mkdir(parents=True)
        reported_path.write_text("other\n", encoding="utf-8")
        return SimpleNamespace(
            board_path=str(reported_path),
            exit_code=0,
            message="rebuilt",
        )

    monkeypatch.setattr(rebuild_mod, "rebuild", fake_rebuild)
    monkeypatch.setattr(
        rebuild_mod,
        "resolve_main_repo_root",
        lambda _repo_arg=None: tmp_path,
    )

    with pytest.raises(RuntimeError, match=r"\.yoke/BOARD\.md"):
        art.rebuild_board(tmp_path)


def test_after_apply_marks_report_failed_when_board_rebuild_fails(
    tmp_path: Path,
    monkeypatch,
):
    from yoke_cli.config import onboard_apply_report
    from yoke_core.domain import json_helper

    report_path = tmp_path / "report.json"
    report_path.write_text(json_helper.dumps_compact({
        "run_id": "run-test",
        "steps": [{
            "step_id": "10-project-write-board-art",
            "action": "project-write-board-art",
            "target": "",
            "status": "done",
            "started_at": None,
            "finished_at": None,
            "error": None,
        }],
        "final_status": "done",
        "resume_command": onboard_apply_report.RESUME_COMMAND,
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        art, "rebuild_board",
        lambda _repo_root: (_ for _ in ()).throw(RuntimeError("no board")),
    )
    shell = _BoardArtShell()
    report = {
        "project_onboarding": {"checkout": str(tmp_path)},
        "apply_report": {"path": str(report_path)},
    }

    with pytest.raises(WizardApplyError) as raised:
        shell._board_art_after_apply(report)

    assert raised.value.failed_step == "10-project-write-board-art"
    payload = json_helper.loads_text(report_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == "failed"
    assert payload["failed_step"] == "10-project-write-board-art"
    assert payload["steps"][0]["status"] == "failed"
    assert payload["steps"][0]["error"] == "no board"


class _BoardArtShell(BoardArtFlow):
    def __init__(self) -> None:
        self.result = WizardResult(
            config_path="cfg",
            env_name="prod",
            api_url="https://x",
            project_checkout="",
            board_art_word="EXT",
            board_art_variants=[
                art.generate_variant(
                    kind="ASCII",
                    word="EXT",
                    seed_text="seed",
                    attempt=0,
                )
            ],
        )
        self.report_path = None
        self.resume_command = None
        self.goto_views: list = []

    def _board_art_view(self, step, builder, on_select):
        return {"step": step, "builder": builder, "on_select": on_select}

    def _goto(self, view):
        self.goto_views.append(view)
