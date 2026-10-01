"""Unsupported libc is refused before downloads or package installation."""

from pathlib import Path

import pytest

from public_installer_helpers import (
    FAKE_INSTALL_PY,
    linux_stub_bin,
    load_installer,
    run_shim,
    write_executable,
    write_uv_stub,
)


@pytest.mark.parametrize("uv_present", [False, True])
def test_shim_refuses_musl_before_any_download(tmp_path: Path, uv_present: bool):
    bin_dir = linux_stub_bin(tmp_path)
    write_executable(bin_dir / "ldd", "#!/bin/sh\nprintf 'musl libc\\n' >&2\nexit 1\n")
    download_marker = tmp_path / "downloaded"
    write_executable(bin_dir / "curl", f"#!/bin/sh\ntouch '{download_marker}'\n")
    if uv_present:
        write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)

    result = run_shim(bin_dir, args=("--yes",))

    assert result.returncode == 1
    assert "unsupported_libc" in result.stderr
    assert "Alpine" in result.stderr
    assert "glibc Linux" in result.stderr
    assert "Ubuntu, Debian, or Fedora" in result.stderr
    assert "rerun" in result.stderr
    assert not download_marker.exists()
    assert "FAKE_INSTALL_RAN" not in result.stdout


@pytest.mark.parametrize(
    "libc,loaders",
    [
        ("musl", []),
        ("", ["/lib/ld-musl-aarch64.so.1"]),
        ("libc", ["/lib/ld-musl-x86_64.so.1"]),
    ],
)
def test_python_helper_refuses_musl_before_version_resolution(
    monkeypatch, libc, loaders
):
    installer = load_installer()
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.platform, "libc_ver", lambda: (libc, ""))
    monkeypatch.setattr(installer.glob, "glob", lambda pattern: loaders)

    def unexpected_download(_url):
        pytest.fail("musl refusal must precede version resolution")

    runner = installer.Installer(installer.parse_args([]), fetcher=unexpected_download)
    with pytest.raises(installer.InstallError, match="unsupported_libc.*glibc Linux"):
        runner.run()


def test_python_helper_allows_glibc_with_musl_loader_installed(monkeypatch, capsys):
    installer = load_installer()
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.platform, "libc_ver", lambda: ("glibc", "2.36"))
    monkeypatch.setattr(
        installer.glob, "glob", lambda pattern: ["/lib/ld-musl-x86_64.so.1"]
    )
    options = installer.parse_args(["--dry-run", "--version", "1.2.3"])

    installer.Installer(options).run()

    assert "Resolved Yoke 1.2.3" in capsys.readouterr().out


@pytest.mark.parametrize(
    "os_name,banner", [("Linux", "ldd (GNU libc) 2.36"), ("Darwin", "musl libc")]
)
def test_shim_allows_supported_hosts(tmp_path: Path, os_name: str, banner: str):
    bin_dir = linux_stub_bin(tmp_path)
    write_executable(bin_dir / "uname", f"#!/bin/sh\nprintf '{os_name}'\n")
    write_executable(bin_dir / "ldd", f"#!/bin/sh\nprintf '{banner}'\n")
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)

    result = run_shim(bin_dir)

    assert result.returncode == 0, result.stderr
    assert "FAKE_INSTALL_RAN" in result.stdout
