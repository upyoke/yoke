"""Login and SSH PATH-surface coverage for the Test Mac reset program."""

from __future__ import annotations

import os
from pathlib import Path

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment as _assignment,
    function_program as _function_program,
    require_zsh as _require_zsh,
    run_functions as _run_functions,
)
from yoke_cli.config import path_doctor


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_zsh_program_verifies_shells_without_inheriting_dirty_path(
    tmp_path: Path,
) -> None:
    binary = _require_zsh()
    home = tmp_path / "test-home"
    home.mkdir()
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": binary}
    )
    tool_bin = Path(path_state.tool_bin_dir)
    dirty_env = {**os.environ, "PATH": f"{tool_bin}:{os.environ.get('PATH', '')}"}
    lines = (
        _function_program(),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin:/usr/sbin:/sbin"),
        _assignment("tool_bin_dir", str(tool_bin)),
        "tools=(definitely-no-yoke-reset-tool)",
        "shell_surface_is_clean -c || print -r -- SURFACE_DIRTY",
        "shell_surface_is_clean -lic || print -r -- SURFACE_DIRTY",
    )

    result = _run_functions(
        lines,
        shell_home=tmp_path / "shell-home",
        env=dirty_env,
    )

    assert "SURFACE_DIRTY" not in result.stdout, result.stdout + result.stderr


def test_shell_surface_check_reports_a_resolvable_tool(tmp_path: Path) -> None:
    binary = _require_zsh()
    tool_bin = tmp_path / "bin"
    tool_bin.mkdir()
    planted = tool_bin / "yoke-reset-probe"
    planted.write_text("#!/bin/sh\nexit 0\n")
    planted.chmod(0o755)
    dirty_env = {**os.environ, "PATH": f"{tool_bin}:{os.environ.get('PATH', '')}"}
    shell_home = tmp_path / "shell-home"
    _write(shell_home / ".zprofile", f"export PATH={tool_bin}:$PATH\n")
    lines = (
        _function_program(),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin"),
        _assignment("tool_bin_dir", str(tool_bin)),
        "tools=(yoke-reset-probe)",
        "shell_surface_is_clean -lic || print -r -- SURFACE_DIRTY",
    )

    result = _run_functions(lines, shell_home=shell_home, env=dirty_env)

    # The earlier program swallowed this failure inside an unchecked loop, so a
    # dirty surface has to be observable on its own before it can gate anything.
    assert "SURFACE_DIRTY" in result.stdout, result.stdout + result.stderr
