"""Tests for the tool-shaped ``yoke check file-line`` command."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_cli.main import main as cli_main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


class TestCheckFileLineCommand:
    def test_help_lists_and_renders_sanctioned_surface(self, capsys):
        assert cli_main(["--help"]) == 0
        assert "yoke check file-line" in capsys.readouterr().out

        assert cli_main(["check", "file-line", "--help"]) == 0
        out = capsys.readouterr().out
        assert "usage: yoke check file-line" in out
        assert "python3 -m yoke_core.domain.file_line_check" not in out

    def test_clean_staged_change_passes(self, tmp_path, monkeypatch, capsys):
        repo = _init_repo(tmp_path / "repo")
        monkeypatch.chdir(repo)
        (repo / "ok.py").write_text("x = 1\n")
        _git(repo, "add", "ok.py")

        assert cli_main(["check", "file-line", "--staged"]) == 0
        assert "ok: no authored file violations" in capsys.readouterr().out

    def test_oversized_staged_file_blocks(self, tmp_path, monkeypatch, capsys):
        repo = _init_repo(tmp_path / "repo")
        monkeypatch.chdir(repo)
        (repo / "big.py").write_text(
            "\n".join(f"x_{i} = {i}" for i in range(400)) + "\n"
        )
        _git(repo, "add", "big.py")

        assert cli_main(["check", "file-line", "--staged"]) == 1
        out = capsys.readouterr().out
        assert "HARD-FAIL" in out
        assert "big.py" in out

    def test_operation_inventory_marks_command_tool_shaped(self):
        from yoke_cli import operation_inventory as inv

        entry = inv.lookup("yoke check file-line")
        assert entry is not None
        assert entry.status == inv.PERMANENT
        assert entry.reason == inv.REASON_TOOL_SHAPED
