"""Noninteractive and terminal-specific public installer onboarding behavior."""

from __future__ import annotations

from pathlib import Path

from public_installer_helpers import (
    FAKE_INSTALL_PY,
    INSTALL_SHIM_PATH,
    linux_stub_bin,
    run_shim,
    write_executable,
    write_uv_stub,
)


_bin = linux_stub_bin


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
        "Run yoke onboard to finish setting up your machine & projects."
        in result.stdout
    )
    assert "Starting Yoke onboard" not in result.stdout
    assert onboard_log.read_text(encoding="utf-8") == ""


def test_no_onboard_env_suppresses_onboard_offer(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    write_executable(bin_dir / "yoke", "#!/bin/sh\nexit 0\n")

    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_INSTALL_YES": "1", "YOKE_NO_ONBOARD": "1"},
    )

    assert result.returncode == 0
    assert "onboard" not in result.stdout.lower()


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
    assert logged.endswith("onboard --post-install")
    assert "☀ Starting Yoke onboard…" in result.stdout
    assert "New terminal windows already have it." in result.stdout
    assert f'source "{tmp_path}/.zprofile"' in result.stdout


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
    assert "* Starting Yoke onboard..." in result.stdout
    assert "Yoke installation complete." in result.stdout
    assert "  | Run now to use Yoke in this terminal:" in result.stdout
    assert f'  |     source "{tmp_path}/.zprofile"' in result.stdout
    assert "☀" not in result.stdout
    assert "▌" not in result.stdout
    assert "…" not in result.stdout


def test_successful_interactive_onboard_prints_path_guidance_contract() -> None:
    text = INSTALL_SHIM_PATH.read_text(encoding="utf-8")

    assert "print_path_guidance_after_onboard" in text
    assert "Run now to use Yoke in this terminal:" in text
    assert 'exec "$shell_path" -l' not in text


def test_shim_never_invokes_onboard_project() -> None:
    # Project adoption (`yoke onboard-project`) is a separate post-onboarding
    # step; the public installer shim must never reach it.
    assert "onboard-project" not in INSTALL_SHIM_PATH.read_text(encoding="utf-8")
