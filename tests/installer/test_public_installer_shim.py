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


def test_native_windows_is_unsupported(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_executable(bin_dir / "uname", "#!/bin/sh\nprintf MINGW64_NT-10.0\n")

    result = run_shim(bin_dir)

    assert result.returncode == 1
    assert "is not supported by this installer" in result.stderr
    assert "WSL follows the Linux path" in result.stderr


def test_missing_uv_without_curl_prints_manual_and_rerun(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    # No uv, no curl: cannot install uv, so name the manual command + rerun.
    # Pin PATH to the stub dir only so the host's real uv/curl never leak in and
    # the test cannot trigger a real Astral install.

    result = run_shim(bin_dir, args=("--yes",), env_extra={"PATH": str(bin_dir)})

    assert result.returncode == 1
    assert "uv/uvx is required and curl is missing" in result.stderr
    assert "Install curl first" in result.stderr
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in result.stderr
    assert (
        "curl -fsSL https://example.invalid/install | bash -s -- --yes"
        in result.stderr
    )


def test_declining_uv_consent_prints_manual_and_rerun(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    prompt_in = tmp_path / "prompt-in"
    prompt_out = tmp_path / "prompt-out"
    prompt_in.write_text("n\n", encoding="utf-8")
    prompt_out.write_text("", encoding="utf-8")
    write_executable(bin_dir / "curl", "#!/bin/sh\nexit 0\n")

    # NO_COLOR pins the friendly decline screen to plain text we can assert on.
    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "NO_COLOR": "1",
            "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
            "YOKE_INSTALL_PROMPT_OUT": str(prompt_out),
        },
        input_text="",
    )

    assert result.returncode == 1
    # The branded welcome + consent and the friendly decline screen all render to
    # stdout (golden-tested); the screen never dead-ends — it names the manual
    # install and the exact rerun command.
    assert "Yoke's only prerequisite — uv/uvx — isn't installed yet." in result.stdout
    assert "uv/uvx is required to install Yoke." in result.stdout
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in result.stdout
    assert "curl -fsSL https://example.invalid/install | bash" in result.stdout


def test_missing_uv_installs_via_astral_on_consent(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    log = tmp_path / "commands.log"
    # curl is the Astral installer here: it drops a uv that serves the fake
    # install.py and exits cleanly on handoff.
    write_executable(
        bin_dir / "curl",
        "#!/bin/sh\n"
        f"printf 'curl %s\\n' \"$*\" >> '{log}'\n"
        f"cat > '{bin_dir}/uv' <<'UVSTUB'\n"
        "#!/bin/sh\n"
        'if [ "$1" = "run" ]; then\n'
        "  shift\n"
        '  while [ "$#" -gt 0 ]; do\n'
        '    case "$1" in\n'
        "      --no-project|--project|python) shift ;;\n"
        "      *) break ;;\n"
        "    esac\n"
        "  done\n"
        '  if [ -n "${INSTALLER_OUT:-}" ]; then\n'
        # \047 (octal ') is POSIX-portable; \x27 (hex) is a bashism the runner's
        # /bin/sh (dash) leaves literal, yielding a Python SyntaxError.
        '    printf "print(\\047HANDOFF_OK\\047)\\n" > "$INSTALLER_OUT"\n'
        "    exit 0\n"
        "  fi\n"
        '  exec python3 "$@"\n'
        "fi\n"
        "exit 0\n"
        "UVSTUB\n"
        f"chmod +x '{bin_dir}/uv'\n",
    )

    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_INSTALL_YES": "1"},
    )

    rendered_log = log.read_text(encoding="utf-8")
    assert "astral.sh/uv/install.sh" in rendered_log
    assert result.returncode == 0
    assert "HANDOFF_OK" in result.stdout


def test_present_uv_hands_off_to_install_py(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)

    result = run_shim(
        bin_dir,
        args=("--yes", "--channel", "latest"),
        env_extra={"YOKE_INSTALL_YES": "1"},
    )

    assert result.returncode == 0
    # The shim forwards the parsed flags to install.py.
    assert "FAKE_INSTALL_RAN" in result.stdout
    assert "--channel latest" in result.stdout
    assert "--yes" in result.stdout


def test_dry_run_forwards_dry_run_flag_to_helper(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)

    result = run_shim(bin_dir, args=("--dry-run",))

    assert result.returncode == 0
    assert "FAKE_INSTALL_RAN" in result.stdout
    assert "--dry-run" in result.stdout
    # onboarding is never offered on a dry run.
    assert "onboard" not in result.stdout.lower()


def test_uv_install_prompt_reads_dev_tty_under_pipe(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    prompt_in = tmp_path / "prompt-in"
    prompt_out = tmp_path / "prompt-out"
    prompt_in.write_text("y\n", encoding="utf-8")
    prompt_out.write_text("", encoding="utf-8")
    log = tmp_path / "commands.log"
    # curl serves both the Astral install AND a uv that hands off cleanly.
    write_executable(
        bin_dir / "curl",
        "#!/bin/sh\n"
        f"printf 'curl %s\\n' \"$*\" >> '{log}'\n"
        f"cat > '{bin_dir}/uv' <<'UVSTUB'\n"
        "#!/bin/sh\n"
        'if [ "$1" = "run" ]; then\n'
        "  shift\n"
        '  while [ "$#" -gt 0 ]; do\n'
        '    case "$1" in\n'
        "      --no-project|--project|python) shift ;;\n"
        "      *) break ;;\n"
        "    esac\n"
        "  done\n"
        '  if [ -n "${INSTALLER_OUT:-}" ]; then\n'
        # \047 (octal ') is POSIX-portable; \x27 (hex) is a bashism the runner's
        # /bin/sh (dash) leaves literal, yielding a Python SyntaxError.
        '    printf "print(\\047HANDOFF_OK\\047)\\n" > "$INSTALLER_OUT"\n'
        "    exit 0\n"
        "  fi\n"
        '  exec python3 "$@"\n'
        "fi\n"
        "exit 0\n"
        "UVSTUB\n"
        f"chmod +x '{bin_dir}/uv'\n",
    )

    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
            "YOKE_INSTALL_PROMPT_OUT": str(prompt_out),
        },
        input_text="payload that must not be consumed by the prompt\n",
    )

    # The consent is rendered to stdout; the answer is read from the tty-in file,
    # never from the stdin pipe — so consent proceeds (uv installs) and the
    # piped payload is left untouched.
    assert "isn't installed yet." in result.stdout
    assert result.returncode == 0
    assert "astral.sh/uv/install.sh" in log.read_text(encoding="utf-8")


def test_interactive_success_auto_launches_onboard_without_gate(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    prompt_in = tmp_path / "prompt-in"
    prompt_out = tmp_path / "prompt-out"
    onboard_log = tmp_path / "onboard.log"
    prompt_in.write_text("y\n", encoding="utf-8")
    prompt_out.write_text("", encoding="utf-8")
    write_executable(
        bin_dir / "yoke",
        "#!/bin/sh\n"
        f"printf 'yoke %s\\n' \"$*\" >> '{onboard_log}'\n",
    )

    result = run_shim(
        bin_dir,
        args=(),
        env_extra={
            "TERM": "xterm-256color",
            "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
            "YOKE_INSTALL_PROMPT_OUT": str(prompt_out),
        },
    )

    assert result.returncode == 0
    # The separate onboarding consent gate is gone: success launches the wizard
    # directly, no extra prompt.
    assert "Start Yoke onboarding now" not in prompt_out.read_text(encoding="utf-8")
    assert "Start Yoke onboarding now" not in result.stdout
    assert "☀ Starting Yoke onboard…" in result.stdout
    assert "yoke onboard --post-install" in onboard_log.read_text(encoding="utf-8")


def test_yes_mode_prints_next_without_launching_onboard(tmp_path: Path) -> None:
    bin_dir = _bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    onboard_log = tmp_path / "onboard.log"
    onboard_log.write_text("", encoding="utf-8")
    write_executable(
        bin_dir / "yoke",
        "#!/bin/sh\n"
        f"printf 'yoke %s\\n' \"$*\" >> '{onboard_log}'\n",
    )

    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_INSTALL_YES": "1"},
    )

    assert result.returncode == 0
    assert "Run yoke onboard to finish setting up your machine & projects." in result.stdout
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
        "#!/bin/sh\n"
        f"printf '%s %s\\n' \"$0\" \"$*\" >> '{launch_log}'\n",
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
    assert "exec \"$shell_path\" -l" not in text


def test_shim_never_invokes_onboard_project() -> None:
    # Project adoption (`yoke onboard-project`) is a separate post-onboarding
    # step; the public installer shim must never reach it.
    assert "onboard-project" not in INSTALL_SHIM_PATH.read_text(encoding="utf-8")
