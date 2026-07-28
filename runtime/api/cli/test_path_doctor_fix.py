from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters import path_doctor as adapter
from yoke_cli.config.path_doctor import ToolResolution


def test_path_fix_writes_login_and_ssh_targets_on_the_first_run(
    monkeypatch,
    capsys,
) -> None:
    login = Path("/Users/tester/.zprofile")
    ssh = Path("/Users/tester/.zshenv")
    applied: list[Path] = []
    diagnosis = SimpleNamespace(
        current_shell="zsh",
        tool_bin_dir="/Users/tester/.local/bin",
        startup_file=str(login),
        ssh_needs_fix=True,
        ssh_startup_file=str(ssh),
    )
    resolved = [
        ToolResolution("uv", "/Users/tester/.local/bin/uv"),
        ToolResolution("yoke", "/Users/tester/.local/bin/yoke"),
    ]

    monkeypatch.setattr(adapter.doctor, "diagnose", lambda: diagnosis)
    monkeypatch.setattr(
        adapter.doctor,
        "render_managed_block",
        lambda _bindir: "managed block",
    )

    def apply_fix(target: Path, _bindir: str) -> bool:
        applied.append(target)
        return True

    monkeypatch.setattr(adapter.doctor, "apply_fix", apply_fix)
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda _shell: resolved,
    )
    monkeypatch.setattr(
        adapter.doctor,
        "verify_ssh_command",
        lambda _shell: resolved,
    )

    assert adapter.path_fix(["--yes", "--json"]) == 0
    assert applied == [login, ssh]
    assert '"ssh_verified": true' in capsys.readouterr().out
