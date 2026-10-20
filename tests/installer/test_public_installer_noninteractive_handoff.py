from __future__ import annotations

import json
from pathlib import Path

import pytest

from public_installer_helpers import (
    FAKE_INSTALL_PY,
    linux_stub_bin,
    run_shim,
    write_executable,
    write_uv_stub,
)

QUESTION = {"setup": "agent", "version": 1, "state": "question", "key": "connect.destination"}


def _agent_yoke(tmp_path: Path, *, status: int = 0) -> tuple[Path, Path, Path]:
    bin_dir = linux_stub_bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    onboard_log = tmp_path / "onboard.log"
    stdin_log = tmp_path / "stdin.log"
    onboard_log.write_text("", encoding="utf-8")
    line = json.dumps(QUESTION)
    write_executable(
        bin_dir / "yoke",
        "#!/bin/sh\n"
        f"printf 'yoke %s\\n' \"$*\" >> '{onboard_log}'\n"
        f"cat > '{stdin_log}'\n"
        f"printf '%s\\n' '{line}'\n"
        f"exit {status}\n",
    )
    return bin_dir, onboard_log, stdin_log


def test_without_a_terminal_setup_starts_in_agent_mode(tmp_path: Path) -> None:
    bin_dir, onboard_log, stdin_log = _agent_yoke(tmp_path)

    result = run_shim(bin_dir, args=(), input_text="answers the agent never typed\n")

    assert result.returncode == 0
    assert onboard_log.read_text(encoding="utf-8").endswith(
        "yoke setup --agent --post-install\n"
    )
    assert stdin_log.read_text(encoding="utf-8") == ""
    json_lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert [json.loads(line) for line in json_lines] == [QUESTION]
    assert "Starting Yoke setup" not in result.stdout


@pytest.mark.parametrize("status", [1, 2])
def test_the_install_exit_status_follows_agent_setup(tmp_path: Path, status: int) -> None:
    bin_dir, _, _ = _agent_yoke(tmp_path, status=status)

    result = run_shim(bin_dir, args=())

    assert result.returncode == status


def test_yes_prints_the_agent_aware_next_command(tmp_path: Path) -> None:
    bin_dir, onboard_log, _ = _agent_yoke(tmp_path)

    result = run_shim(bin_dir, args=("--yes",), env_extra={"YOKE_INSTALL_YES": "1"})

    assert result.returncode == 0
    assert (
        "Run yoke setup in a terminal, or yoke setup --agent from an agent."
        in result.stdout
    )
    assert onboard_log.read_text(encoding="utf-8") == ""


def test_no_setup_skips_agent_mode(tmp_path: Path) -> None:
    bin_dir, onboard_log, _ = _agent_yoke(tmp_path)

    result = run_shim(bin_dir, args=("--no-setup",))

    assert result.returncode == 0
    assert onboard_log.read_text(encoding="utf-8") == ""
    assert "yoke setup --agent" not in result.stdout


def test_skip_harness_permissions_reaches_agent_setup(tmp_path: Path) -> None:
    bin_dir, onboard_log, _ = _agent_yoke(tmp_path)

    result = run_shim(bin_dir, args=("--skip-harness-permissions",))

    assert result.returncode == 0
    assert onboard_log.read_text(encoding="utf-8").endswith(
        "yoke setup --agent --post-install --skip-harness-permissions\n"
    )


def test_skip_harness_permissions_is_named_in_the_yes_next_command(
    tmp_path: Path,
) -> None:
    bin_dir, onboard_log, _ = _agent_yoke(tmp_path)

    result = run_shim(
        bin_dir,
        args=("--yes", "--skip-harness-permissions"),
        env_extra={"YOKE_INSTALL_YES": "1"},
    )

    assert result.returncode == 0
    assert (
        "Run yoke setup --skip-harness-permissions in a terminal, or yoke setup "
        "--agent --skip-harness-permissions from an agent." in result.stdout
    )
    assert onboard_log.read_text(encoding="utf-8") == ""


def test_help_lists_skip_harness_permissions(tmp_path: Path) -> None:
    bin_dir, _, _ = _agent_yoke(tmp_path)

    result = run_shim(bin_dir, args=("--help",))

    assert result.returncode == 0
    assert "[--skip-harness-permissions]" in result.stdout
