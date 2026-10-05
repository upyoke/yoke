"""Truthful-action and timeout coverage for the shell uv bootstrap."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from public_installer_helpers import (
    FAKE_INSTALL_PY,
    linux_stub_bin,
    run_shim,
    write_executable,
    write_uv_stub,
)


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
    assert "Installing uv" in result.stdout
    assert action in result.stderr
    assert "brew install uv" not in result.stdout
    assert "brew install uv" not in result.stderr
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


@pytest.mark.parametrize("times_out", [False, True])
def test_uv_bootstrap_without_ps(tmp_path: Path, times_out: bool) -> None:
    bin_dir = linux_stub_bin(tmp_path)
    # Restrict PATH to the bootstrap's actual commands; ps is absent, rather
    # than a stub that would still satisfy command -v.
    for name in ("cat", "chmod", "cp", "env", "mktemp", "rm", "rmdir", "sleep"):
        executable = shutil.which(name)
        assert executable is not None
        (bin_dir / name).symlink_to(executable)
    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    staged_uv = write_uv_stub(staged_dir, install_py_body=FAKE_INSTALL_PY)
    bootstrap = "exec sleep 30" if times_out else f"cp '{staged_uv}' '{bin_dir / 'uv'}'"
    write_executable(
        bin_dir / "curl",
        f"#!/bin/sh\ncat <<'BOOTSTRAP'\n#!/bin/sh\n{bootstrap}\nBOOTSTRAP\n",
    )

    started = time.monotonic()
    result = run_shim(
        bin_dir,
        args=("--yes", "--no-setup"),
        env_extra={"PATH": str(bin_dir), "YOKE_UV_BOOTSTRAP_TIMEOUT_SECONDS": "1"},
    )

    assert time.monotonic() - started < 5
    assert "ps is missing" not in result.stderr
    if times_out:
        assert result.returncode == 1
        assert "uv bootstrap timed out after 1s" in result.stderr
        assert "then rerun" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert "FAKE_INSTALL_RAN" in result.stdout
