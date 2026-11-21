"""Noninteractive and terminal-specific public installer onboarding behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from public_installer_helpers import (
    FAKE_INSTALL_PY,
    FAKE_INSTALL_WITH_SETUP_REPORT,
    INSTALL_SHIM_PATH,
    linux_stub_bin,
    run_shim,
    write_executable,
    write_uv_stub,
)

SHIM_BRANCH = pytest.mark.posix_only(
    reason="POSIX install shim branch; Windows installs through install.ps1"
)


_bin = linux_stub_bin


@SHIM_BRANCH
def test_yes_mode_prints_next_without_launching_onboard(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    onboard_log = tmp_path / "onboard.log"
    onboard_log.write_text("", encoding="utf-8")
    write_executable(
        bin_dir / "yoke",
        f"#!/bin/sh\nprintf 'yoke %s\\n' \"$*\" >> '{onboard_log}'\n",
    )

    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_INSTALL_YES": "1"},
    )

    assert result.returncode == 0
    assert (
        "Run yoke setup in a terminal, or yoke setup --agent from an agent."
        in result.stdout
    )
    assert "Starting Yoke setup" not in result.stdout
    assert onboard_log.read_text(encoding="utf-8") == ""


@SHIM_BRANCH
def test_no_setup_env_suppresses_onboard_offer(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    write_executable(bin_dir / "yoke", "#!/bin/sh\nexit 0\n")

    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_INSTALL_YES": "1", "YOKE_NO_SETUP": "1"},
    )

    assert result.returncode == 0
    assert "Starting Yoke setup" not in result.stdout
    assert "Run yoke setup" not in result.stdout


@SHIM_BRANCH
def test_interactive_success_launches_onboard_by_absolute_path(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    prompt_in = tmp_path / "prompt-in"
    prompt_out = tmp_path / "prompt-out"
    launch_log = tmp_path / "launch.log"
    prompt_in.write_text("y\n", encoding="utf-8")
    prompt_out.write_text("", encoding="utf-8")
    # The fake records $0 (its own invocation path) plus its args so we can
    # assert the shim launched yoke by absolute path.
    write_executable(
        bin_dir / "yoke",
        f"#!/bin/sh\nprintf '%s %s\\n' \"$0\" \"$*\" >> '{launch_log}'\n",
    )

    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "HOME": str(tmp_path),
            "SHELL": "/bin/zsh",
            "TERM": "xterm-256color",
            "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
            "YOKE_INSTALL_PROMPT_OUT": str(prompt_out),
        },
    )

    assert result.returncode == 0
    logged = launch_log.read_text(encoding="utf-8").strip()
    launched_path = logged.split(" ", 1)[0]
    assert launched_path.startswith("/")
    assert launched_path.endswith("/yoke")
    assert logged.endswith("setup --post-install")
    assert "☀ Starting Yoke setup…" in result.stdout
    assert "Next: bring your existing work into Yoke." in result.stdout
    assert "(uv updated your shell configuration)" in result.stdout
    assert "1  open a new terminal" in result.stdout
    assert (
        "2  open Claude Code, Codex, or Cursor in your project folder" in result.stdout
    )
    assert "/yoke onboard" in result.stdout
    assert "/yoke onboard (Claude Code/Cursor)" not in result.stdout
    # The reload is a prerequisite of the harness step, so it has to come first;
    # a harness opened before it inherits the pre-install PATH and cannot find
    # yoke. This block is also the last thing on screen, so nothing downstream
    # can restate the order.
    assert result.stdout.index("open a new terminal") < result.stdout.index(
        "open Claude Code, Codex, or Cursor"
    )
    assert result.stdout.index(
        "open Claude Code, Codex, or Cursor"
    ) < result.stdout.index("/yoke onboard")


@SHIM_BRANCH
def test_screen_mode_success_guidance_uses_ascii_glyphs(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    prompt_in = tmp_path / "prompt-in"
    prompt_out = tmp_path / "prompt-out"
    prompt_in.write_text("y\n", encoding="utf-8")
    prompt_out.write_text("", encoding="utf-8")
    write_executable(bin_dir / "yoke", "#!/bin/sh\nexit 0\n")

    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "HOME": str(tmp_path),
            "SHELL": "/bin/zsh",
            "STY": "1234.yoke-test",
            "TERM": "screen-256color",
            "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
            "YOKE_INSTALL_PROMPT_OUT": str(prompt_out),
        },
    )

    assert result.returncode == 0
    assert "* Starting Yoke setup..." in result.stdout
    assert "Yoke installation complete." in result.stdout
    assert "  | Next: bring your existing work into Yoke." in result.stdout
    assert "  |   1  open a new terminal" in result.stdout
    assert "  |   3  use the installed yoke skill:" in result.stdout
    assert "/yoke onboard" in result.stdout
    assert "☀" not in result.stdout
    assert "▌" not in result.stdout
    assert "…" not in result.stdout


def test_successful_interactive_onboard_prints_path_guidance_contract() -> None:
    text = INSTALL_SHIM_PATH.read_text(encoding="utf-8")

    assert "print_path_guidance_after_onboard" in text
    assert "Next: bring your existing work into Yoke." in text
    assert "/yoke onboard" in text
    assert 'exec "$shell_path" -l' not in text


@SHIM_BRANCH
def test_handoff_omits_reload_step_when_calling_shell_already_resolves_yoke(
    tmp_path: Path,
) -> None:
    # A shell that already has the tool bin dir needs no reload, so the block
    # drops that step and the harness step becomes 1. The installer prepends the
    # dir to its own PATH before anything runs, so this can only be decided from
    # the PATH snapshot taken at entry.
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    tool_bin_dir = tmp_path / ".local" / "bin"
    tool_bin_dir.mkdir(parents=True)
    prompt_in = tmp_path / "prompt-in"
    prompt_out = tmp_path / "prompt-out"
    prompt_in.write_text("y\n", encoding="utf-8")
    prompt_out.write_text("", encoding="utf-8")
    write_executable(bin_dir / "yoke", "#!/bin/sh\nexit 0\n")

    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "HOME": str(tmp_path),
            "SHELL": "/bin/zsh",
            "TERM": "xterm-256color",
            "PATH": ":".join([str(bin_dir), str(tool_bin_dir), "/usr/bin", "/bin"]),
            "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
            "YOKE_INSTALL_PROMPT_OUT": str(prompt_out),
        },
    )

    assert result.returncode == 0
    assert "Next: bring your existing work into Yoke." in result.stdout
    assert "open a new terminal" not in result.stdout
    assert "uv updated your shell configuration" not in result.stdout
    assert (
        "1  open Claude Code, Codex, or Cursor in your project folder" in result.stdout
    )
    assert "2  use the installed yoke skill:" in result.stdout
    assert "/yoke onboard" in result.stdout


def test_shim_hands_off_adoption_to_the_harness() -> None:
    # Execution-readiness is the harness skill's job. The shim only PRINTS the
    # `/yoke onboard` handoff line; it must never execute a slash-command skill
    # itself (the only onboarding the shim may launch is the terminal wizard).
    text = INSTALL_SHIM_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "/yoke onboard" in line:
            assert "printf" in line or line.lstrip().startswith("#"), (
                "the shim may only print the /yoke onboard handoff, "
                f"never run it: {line.strip()}"
            )


@SHIM_BRANCH
@pytest.mark.parametrize("os_name", ["Darwin", "Linux"])
@pytest.mark.parametrize("path_loaded", [False, True])
@pytest.mark.parametrize(
    "status, exit_code, token", [(130, 0, "setup_skipped"), (1, 2, "setup_failed")]
)
def test_shim_reports_post_install_setup_exit(
    tmp_path, os_name, path_loaded, status, exit_code, token
):
    bin_dir = _bin(tmp_path)
    write_executable(bin_dir / "uname", f"#!/bin/sh\nprintf '%s\\n' {os_name}\n")
    install_bin = bin_dir if path_loaded else tmp_path / "tool bin"
    install_bin.mkdir(exist_ok=True)
    write_uv_stub(
        bin_dir,
        install_py_body=FAKE_INSTALL_WITH_SETUP_REPORT,
        tool_bin_dir=install_bin,
    )
    yoke_bin = install_bin / "yoke"
    write_executable(
        yoke_bin,
        "#!/bin/sh\n"
        "if [ \"$1\" = --version ]; then printf '1.2.3\\n'; exit 0; fi\n"
        f"exit {status}\n",
    )
    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "YOKE_INSTALL_PROMPT_IN": "/dev/null",
            "YOKE_INSTALL_PROMPT_OUT": "/dev/null",
        },
    )
    output = result.stdout + result.stderr
    assert result.returncode == exit_code, output
    assert f"{token}: Yoke v1.2.3 is installed" in output
    assert (
        "resume with yoke setup" if path_loaded else f"resume with '{yoke_bin}' setup"
    ) in output
    assert "setup_incomplete" not in output
    assert "yoke_install_failed" not in output
    assert "did not finish" not in output
    assert ("setup_failed" in output) == (exit_code == 2)
    assert "Next: bring your existing work into Yoke" not in output


@SHIM_BRANCH
def test_shim_preserves_install_failure_without_starting_setup(tmp_path):
    bin_dir = _bin(tmp_path)
    write_uv_stub(
        bin_dir, install_py_body="print('install_failure_fixture'); raise SystemExit(1)"
    )
    write_executable(bin_dir / "yoke", "#!/bin/sh\nprintf 'UNEXPECTED_SETUP\\n'\n")

    result = run_shim(bin_dir, args=())
    assert result.returncode == 1
    assert "install_failure_fixture" in result.stdout
    assert "UNEXPECTED_SETUP" not in result.stdout
    assert "setup_skipped" not in result.stdout
    assert "setup_failed" not in result.stdout
