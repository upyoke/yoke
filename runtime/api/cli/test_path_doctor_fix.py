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
    )
    plan = {
        "shell": "zsh",
        "tool_bin_dir": "/Users/tester/.local/bin",
        "login_file": str(login),
        "ssh_file": str(ssh),
        "directories": ["/Users/tester/.local/bin"],
        "directory_tools": {
            "/Users/tester/.local/bin": ["uv", "uvx", "yoke"],
        },
        "harness_clis": [],
        "unresolved_harness_clis": [],
        "targets": [
            {"surface": "login", "path": str(login)},
            {"surface": "ssh", "path": str(ssh)},
        ],
    }
    resolved = [
        ToolResolution("uv", "/Users/tester/.local/bin/uv"),
        ToolResolution("yoke", "/Users/tester/.local/bin/yoke"),
    ]

    monkeypatch.setattr(adapter.doctor, "diagnose", lambda: diagnosis)
    monkeypatch.setattr(adapter.path_repair_plan, "build", lambda _diag: plan)
    monkeypatch.setattr(
        adapter.doctor,
        "render_managed_block",
        lambda _directories: "managed block",
    )

    def apply_fix(target: Path, _directories) -> bool:
        applied.append(target)
        return True

    monkeypatch.setattr(adapter.doctor, "apply_fix", apply_fix)
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda _shell, **_kwargs: resolved,
    )
    monkeypatch.setattr(
        adapter.doctor,
        "verify_ssh_command",
        lambda _shell, **_kwargs: resolved,
    )

    assert adapter.path_fix(["--yes", "--json"]) == 0
    assert applied == [login, ssh]
    output = capsys.readouterr().out
    assert '"login_verified": true' in output
    assert '"ssh_verified": true' in output
