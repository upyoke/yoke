"""Integration coverage for manifest-driven harness CLI PATH repair."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from yoke_cli.config import path_doctor as doctor
from yoke_cli.config import path_repair_plan


def _resolution(executable: str, path: str | None):
    harness_id = {
        "claude": "claude-code",
        "codex": "codex",
        "cursor-agent": "cursor",
    }[executable]
    return doctor.HarnessCliResolution(
        harness_id,
        f"{harness_id.removesuffix('-code')}-cli",
        executable,
        path,
        "path" if path else "missing",
    )


def _write_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


def test_repair_makes_installed_harness_resolve_in_login_and_ssh(
    tmp_path,
    monkeypatch,
):
    zsh = shutil.which("zsh")
    if not zsh:
        pytest.skip("zsh is required to exercise login and non-login startup files")
    tool_dir = tmp_path / ".local" / "bin"
    harness_dir = tmp_path / "vendor" / "bin"
    for executable in (tool_dir / "yoke", tool_dir / "uv", harness_dir / "codex"):
        _write_executable(executable)
    monkeypatch.setattr(
        doctor,
        "resolve_harness_clis",
        lambda _path: (
            _resolution("claude", None),
            _resolution("codex", str(harness_dir / "codex")),
            _resolution("cursor-agent", None),
        ),
    )
    env = {
        "HOME": str(tmp_path),
        "SHELL": zsh,
        "PATH": os.pathsep.join((str(tool_dir), str(harness_dir), "/usr/bin", "/bin")),
    }

    diagnosis = doctor.diagnose(env=env, home=tmp_path)
    plan = path_repair_plan.build(diagnosis)
    targets = [Path(raw) for raw in path_repair_plan.target_paths(plan)]
    assert targets == [tmp_path / ".zprofile", tmp_path / ".zshenv"]
    for target in targets:
        assert doctor.apply_fix(target, plan["directories"])
    for target in targets:
        assert not doctor.apply_fix(target, plan["directories"])

    login = doctor.verify_fresh_login(
        "zsh", env=env, managed_path_dirs=plan["directories"]
    )
    ssh = doctor.verify_ssh_command(
        "zsh", env=env, managed_path_dirs=plan["directories"]
    )
    assert path_repair_plan.verification_ok(login, plan)
    assert path_repair_plan.verification_ok(ssh, plan)
    assert {row.name: row.path for row in login}["codex"] == str(harness_dir / "codex")


def test_repair_empty_harness_case_is_idempotent_and_rerunnable(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        doctor,
        "resolve_harness_clis",
        lambda _path: tuple(
            _resolution(executable, None) for executable in doctor.HARNESS_CLIS
        ),
    )
    diagnosis = doctor.diagnose(
        env={"HOME": str(tmp_path), "SHELL": "/bin/zsh", "PATH": "/usr/bin:/bin"},
        home=tmp_path,
    )
    plan = path_repair_plan.build(diagnosis)

    for target in map(Path, path_repair_plan.target_paths(plan)):
        assert doctor.apply_fix(target, plan["directories"])
        assert not doctor.apply_fix(target, plan["directories"])
    assert "Not installed yet: claude, codex, cursor-agent" in " ".join(
        path_repair_plan.description_lines(plan)
    )
