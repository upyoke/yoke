"""Apply-time board-art materialization and close-out for ``yoke onboard``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_wizard_board_art as art  # noqa: E402
from yoke_cli.config import onboard_wizard_board_art_apply as art_apply  # noqa: E402
from yoke_cli.config.onboard_wizard import (  # noqa: E402
    WizardApplyError,
    WizardResult,
)
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow  # noqa: E402
from yoke_cli.project_install import checkout_gate  # noqa: E402
from yoke_cli.project_install.files import ProjectInstallError  # noqa: E402


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
    assert art_apply.rebuild_board(tmp_path) == board_path
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
        art_apply.rebuild_board(tmp_path)


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
        art_apply.rebuild_board(tmp_path)


def test_after_apply_marks_report_failed_when_board_rebuild_fails(
    tmp_path: Path,
    monkeypatch,
):
    from yoke_core.domain import json_helper

    report_path = tmp_path / "report.json"
    report_path.write_text(_apply_report_payload(), encoding="utf-8")
    monkeypatch.setattr(
        art_apply, "rebuild_board",
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


def test_write_board_art_writes_sections(tmp_path: Path):
    variants = [
        art.generate_variant(kind="ASCII", word="EXT", seed_text="s", attempt=0),
        art.generate_variant(kind="Mixed", word="EXT", seed_text="s", attempt=0),
    ]
    art_apply.write_board_art(tmp_path, "EXT", variants)
    content = (tmp_path / ".yoke" / "board-art").read_text(encoding="utf-8")
    assert "## Master Map" in content
    assert "## ASCII" in content
    assert "## Mixed" in content


def test_repo_root_prefers_report_then_fallback(tmp_path: Path):
    report = {"project_onboarding": {"checkout": str(tmp_path)}}
    assert art_apply.repo_root_from_report(report, "/other") == tmp_path
    structured = {"project_onboarding": {"checkout": {"path": str(tmp_path)}}}
    assert art_apply.repo_root_from_report(structured, "/other") == tmp_path
    assert art_apply.repo_root_from_report({}, str(tmp_path)) == tmp_path
    assert art_apply.repo_root_from_report({}, None) is None

def test_after_apply_hands_over_a_clean_checkout(tmp_path: Path, monkeypatch):
    """A fresh install: Apply commits its art, so nothing is left uncommitted."""
    from yoke_core.domain import json_helper

    root = _installed_checkout(tmp_path / "repo")
    report_path = tmp_path / "report.json"
    report_path.write_text(_apply_report_payload(), encoding="utf-8")
    monkeypatch.setattr(art_apply, "rebuild_board", _write_board_view)
    shell = _BoardArtShell()
    report = {
        "project_onboarding": {
            "checkout": str(root),
            "install": {
                "files_written": [".yoke/board-art"],
                "commit": {"status": "created", "sha": "abc123"},
            },
        },
        "apply_report": {"path": str(report_path)},
    }

    assert shell._board_art_after_apply(report) is True

    assert _git(root, "status", "--porcelain", "--branch").splitlines()[1:] == []
    assert "## Master Map" in (root / ".yoke" / "board-art").read_text(
        encoding="utf-8"
    )
    detail = json_helper.loads_text(
        report_path.read_text(encoding="utf-8")
    )["steps"][0]["detail"]
    assert detail["commit_status"] == "created"
    assert detail["commit_sha"] == _git(root, "rev-parse", "HEAD").strip()
    assert detail["committed_paths"] == [".yoke/board-art"]
    assert ".yoke/board-art" in detail["verified_clean_paths"]


def test_after_apply_over_an_existing_yoke_layer_stays_clean(
    tmp_path: Path, monkeypatch,
):
    """Converging over an installed layer whose art already matches commits
    nothing, and still hands over a clean checkout."""
    root = _installed_checkout(tmp_path / "repo")
    monkeypatch.setattr(art_apply, "rebuild_board", _write_board_view)
    shell = _BoardArtShell()
    report = {"project_onboarding": {"checkout": str(root)}}

    assert shell._board_art_after_apply(report) is True
    head = _git(root, "rev-parse", "HEAD").strip()
    # Second pass over the same checkout: the art is already what Apply writes.
    assert shell._board_art_after_apply(report) is True

    assert _git(root, "rev-parse", "HEAD").strip() == head
    assert _git(root, "status", "--porcelain", "--branch").splitlines()[1:] == []


def test_after_apply_refuses_when_the_art_write_is_left_uncommitted(
    tmp_path: Path, monkeypatch,
):
    """A post-commit write that never got committed is named, not shipped."""
    root = _installed_checkout(tmp_path / "repo")
    monkeypatch.setattr(art_apply, "rebuild_board", _write_board_view)
    monkeypatch.setattr(
        checkout_gate,
        "commit_paths",
        lambda *_args, **_kwargs: {"status": "skipped", "reason": "no-commit"},
    )
    shell = _BoardArtShell()

    with pytest.raises(WizardApplyError) as raised:
        shell._board_art_after_apply(
            {"project_onboarding": {"checkout": str(root)}}
        )

    assert ".yoke/board-art" in str(raised.value)
    assert "git add -A && git commit" in str(raised.value)


def test_commit_board_art_verifies_installer_paths_only_after_it_committed(
    tmp_path: Path,
):
    """An install that deliberately did not commit owns its own dirt."""
    root = _installed_checkout(tmp_path / "repo")
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    art_apply.write_board_art(root, "EXT", [])

    receipt = art_apply.commit_board_art(
        root,
        {"project_onboarding": {"install": {
            "created_settings_files": [".claude/settings.json"],
            "commit": {"status": "skipped", "reason": "no-commit"},
        }}},
    )

    assert receipt["verified_paths"] == [".yoke/board-art"]
    with pytest.raises(ProjectInstallError, match=r"\.claude/settings\.json"):
        art_apply.commit_board_art(
            root,
            {"project_onboarding": {"install": {
                "created_settings_files": [".claude/settings.json"],
                "commit": {"status": "created", "sha": "abc123"},
            }}},
        )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def _installed_checkout(root: Path) -> Path:
    """A checkout as `project install` leaves it: committed, nothing pending."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "yoke@test.invalid")
    _git(root, "config", "user.name", "Yoke Test")
    yoke_dir = root / ".yoke"
    yoke_dir.mkdir()
    (yoke_dir / ".gitignore").write_text("BOARD.md\n", encoding="utf-8")
    (yoke_dir / "board-art").write_text("## Master Map\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Install Yoke operating layer 0.0.0")
    return root


def _write_board_view(repo_root: Path) -> Path:
    """Stand in for the board rebuild: an ignored generated view on disk."""
    board = Path(repo_root) / ".yoke" / "BOARD.md"
    board.write_text("board\n", encoding="utf-8")
    return board


def _apply_report_payload() -> str:
    """The durable report as `finish()` leaves it: the step already marked
    done from the write plan, before the board-art step has actually run."""
    from yoke_cli.config import onboard_apply_report
    from yoke_core.domain import json_helper

    return json_helper.dumps_compact({
        "run_id": "run-test",
        "steps": [{
            "step_id": "10-project-write-board-art",
            "action": art_apply.BOARD_ART_STEP_ACTION,
            "status": "done",
        }],
        "final_status": "done",
        "resume_command": onboard_apply_report.RESUME_COMMAND,
    }) + "\n"


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
