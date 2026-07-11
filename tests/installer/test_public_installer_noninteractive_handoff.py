from __future__ import annotations

from pathlib import Path

from public_installer_helpers import (
    FAKE_INSTALL_PY,
    linux_stub_bin,
    run_shim,
    write_executable,
    write_uv_stub,
)


def test_redirected_success_prints_next_without_launching_onboard(
    tmp_path: Path,
) -> None:
    bin_dir = linux_stub_bin(tmp_path)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    onboard_log = tmp_path / "onboard.log"
    onboard_log.write_text("", encoding="utf-8")
    write_executable(
        bin_dir / "yoke",
        "#!/bin/sh\n"
        f"printf 'yoke %s\\n' \"$*\" >> '{onboard_log}'\n",
    )

    result = run_shim(bin_dir, args=())

    assert result.returncode == 0
    assert "Run yoke onboard to finish setting up your machine & projects." in result.stdout
    assert "Starting Yoke onboard" not in result.stdout
    assert onboard_log.read_text(encoding="utf-8") == ""
