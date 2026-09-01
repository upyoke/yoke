"""Truthful-action and timeout coverage for the shell uv bootstrap."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from public_installer_helpers import linux_stub_bin, run_shim, write_executable


@pytest.mark.parametrize("force_color", ["0", "1"])
def test_consent_and_execution_use_astral_even_when_brew_exists(
    tmp_path: Path, force_color: str
) -> None:
    bin_dir = linux_stub_bin(tmp_path)
    write_executable(bin_dir / "uname", "#!/bin/sh\nprintf Darwin\n")
    brew_log = tmp_path / "brew.log"
    curl_log = tmp_path / "curl.log"
    write_executable(
        bin_dir / "brew",
        f"#!/bin/sh\nprintf called > '{brew_log}'\n",
    )
    write_executable(
        bin_dir / "curl",
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{curl_log}'\n"
        "printf '%s\\n' '#!/bin/sh' 'exit 9'\n",
    )
    prompt_in = tmp_path / "prompt-in"
    prompt_in.write_text("y\n", encoding="utf-8")
    env = {
        "YOKE_INSTALL_FORCE_COLOR": force_color,
        "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
        "YOKE_UV_BOOTSTRAP_TIMEOUT_SECONDS": "2",
    }
    if force_color == "0":
        env["NO_COLOR"] = "1"

    result = run_shim(bin_dir, args=(), env_extra=env)

    action = "curl -LsSf https://astral.sh/uv/install.sh | sh"
    assert result.returncode == 1
    assert action in result.stdout
    assert "brew install uv" not in result.stdout
    assert not brew_log.exists()
    assert "--max-time 2 -- https://astral.sh/uv/install.sh" in curl_log.read_text(
        encoding="utf-8"
    )


def test_uv_installer_execution_times_out_with_recovery(tmp_path: Path) -> None:
    bin_dir = linux_stub_bin(tmp_path)
    write_executable(
        bin_dir / "curl",
        "#!/bin/sh\nprintf '%s\\n' '#!/bin/sh' 'sleep 30'\n",
    )

    started = time.monotonic()
    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_UV_BOOTSTRAP_TIMEOUT_SECONDS": "1"},
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 1
    assert elapsed < 5
    assert "uv bootstrap timed out after 1s" in result.stderr
    assert "install uv manually" in result.stderr
    assert "then rerun" in result.stderr
    assert "Terminated:" not in result.stderr


def test_uv_installer_download_timeout_is_named(tmp_path: Path) -> None:
    bin_dir = linux_stub_bin(tmp_path)
    write_executable(bin_dir / "curl", "#!/bin/sh\nexit 28\n")

    result = run_shim(
        bin_dir,
        args=("--yes",),
        env_extra={"YOKE_UV_BOOTSTRAP_TIMEOUT_SECONDS": "1"},
    )

    assert result.returncode == 1
    assert "uv bootstrap download timed out after 1s" in result.stderr
    assert "Check access to astral.sh" in result.stderr
    assert "then rerun" in result.stderr
