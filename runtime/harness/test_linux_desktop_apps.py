"""Desktop install fixtures publish versions without starting GUI executables."""

from __future__ import annotations

from pathlib import Path
import struct
import subprocess

import pytest

from yoke_harness import linux_appimage_metadata as appimage
from yoke_harness import linux_desktop_apps as apps


@pytest.fixture
def install_layout(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(apps.shutil, "which", lambda _command: None)
    monkeypatch.setattr(apps, "_CURSOR_METADATA_PATHS", (tmp_path / "package.json",))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "system"))
    return tmp_path


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
@pytest.mark.parametrize(
    "surface,package",
    [
        ("claude-desktop", "claude-desktop"),
        ("cursor-desktop", "cursor"),
    ],
)
def test_debian_installed_package_metadata(
    monkeypatch,
    install_layout: Path,
    architecture: str,
    surface: str,
    package: str,
) -> None:
    status = install_layout / "status"
    status.write_text(
        f"Package: {package}\nArchitecture: {architecture}\nVersion: 3.18.2-1\n"
    )
    monkeypatch.setattr(
        apps.shutil,
        "which",
        lambda name: "/usr/bin/dpkg-query" if name == "dpkg-query" else None,
    )

    def query(command, **kwargs):
        assert command == [
            "/usr/bin/dpkg-query",
            "-W",
            "-f=${db:Status-Status}\t${Version}",
            package,
        ]
        assert kwargs["timeout"] == 10
        assert kwargs["env"]["LC_ALL"] == "C"
        version = status.read_text().split("Version: ")[1].strip()
        return subprocess.CompletedProcess(command, 0, f"installed\t{version}", "")

    assert apps.read_linux_desktop_version(
        surface, home=install_layout, runner=query
    ) == ("package", "3.18.2")


def test_removed_debian_package_is_missing(monkeypatch, install_layout: Path) -> None:
    monkeypatch.setattr(apps.shutil, "which", lambda _name: "/usr/bin/dpkg-query")
    with pytest.raises(
        FileNotFoundError, match="desktop_app_missing: install claude-desktop"
    ):
        apps.read_linux_desktop_version(
            "claude-desktop",
            home=install_layout,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 0, "config-files\t3.18.2", ""
            ),
        )


def test_cursor_rpm_metadata(monkeypatch, install_layout: Path) -> None:
    monkeypatch.setattr(
        apps.shutil, "which", lambda name: "/usr/bin/rpm" if name == "rpm" else None
    )

    def query(command, **_kwargs):
        assert command == ["/usr/bin/rpm", "-q", "--qf", "%{VERSION}", "cursor"]
        return subprocess.CompletedProcess(command, 0, "3.18.2", "")

    assert apps.read_linux_desktop_version(
        "cursor-desktop", home=install_layout, runner=query
    ) == ("package", "3.18.2")


def test_rpm_absence_and_database_failure_are_different(
    monkeypatch, install_layout: Path
) -> None:
    monkeypatch.setattr(
        apps.shutil, "which", lambda name: "/usr/bin/rpm" if name == "rpm" else None
    )
    with pytest.raises(FileNotFoundError, match="desktop_app_missing"):
        apps.read_linux_desktop_version(
            "cursor-desktop",
            home=install_layout,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 1, "package cursor is not installed", ""
            ),
        )
    with pytest.raises(
        RuntimeError, match="desktop_package_query_failed.*repair the package database"
    ):
        apps.read_linux_desktop_version(
            "cursor-desktop",
            home=install_layout,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 1, "", "cannot open database"
            ),
        )


def test_installed_version_file_reads_cursor_not_upstream_vscode(
    install_layout: Path,
) -> None:
    (install_layout / "package.json").write_text(
        '{"version":"1.105.0","cursorVersion":"3.18.2"}'
    )
    assert apps.read_linux_desktop_version("cursor-desktop", home=install_layout) == (
        "file",
        "3.18.2",
    )


def _image(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    image = root / "Cursor-renamed.AppImage"
    header = bytearray(256)
    header[:4] = b"\x7fELF"
    header[8:11] = b"AI\x02"
    header[64:68] = b"hsqs"  # A runtime string must not count as a superblock.
    header[128:132] = b"hsqs"
    struct.pack_into("<HH", header, 156, 4, 0)
    image.write_bytes(header)
    metadata = root / appimage.CURSOR_VERSION_FILE
    metadata.parent.mkdir(parents=True)
    metadata.write_text('{"version":"1.105.0","cursorVersion":"3.18.2"}')
    return image


@pytest.mark.parametrize("discovery", ["applications", "desktop-entry", "path"])
def test_cursor_appimage_reads_embedded_metadata(
    monkeypatch,
    install_layout: Path,
    discovery: str,
) -> None:
    image = _image(
        install_layout
        / ("Applications" if discovery == "applications" else "custom space")
    )
    if discovery == "desktop-entry":
        entries = install_layout / "data/applications"
        entries.mkdir(parents=True)
        (entries / "appimagekit-Cursor.desktop").write_text(
            f'[Desktop Entry]\nExec="{image}" --no-sandbox %U\n'
        )
    monkeypatch.setattr(
        apps.shutil,
        "which",
        lambda name: (
            "/usr/bin/unsquashfs"
            if name == "unsquashfs"
            else str(image)
            if name == "cursor" and discovery == "path"
            else None
        ),
    )
    calls = []

    def extract(command, **kwargs):
        calls.append(command)
        assert command == [
            "/usr/bin/unsquashfs",
            "-o",
            "128",
            "-cat",
            str(image),
            appimage.CURSOR_VERSION_FILE,
        ]
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(
            command, 0, (image.parent / command[-1]).read_text(), ""
        )

    assert apps.read_linux_desktop_version(
        "cursor-desktop", home=install_layout, runner=extract
    ) == ("file", "3.18.2")
    assert len(calls) == 1


def test_appimage_without_reader_names_install_recovery(install_layout: Path) -> None:
    image = _image(install_layout / "Applications")
    with pytest.raises(
        RuntimeError, match="cursor_appimage_reader_missing: install squashfs-tools"
    ):
        appimage.read_appimage_version(image)


def test_corrupt_appimage_is_not_reported_missing(install_layout: Path) -> None:
    directory = install_layout / "Applications"
    directory.mkdir()
    (directory / "Cursor.AppImage").write_text("not an image")
    with pytest.raises(ValueError, match="cursor_appimage_invalid"):
        apps.read_linux_desktop_version("cursor-desktop", home=install_layout)


def test_appimage_reader_failure_is_diagnosed(
    monkeypatch, install_layout: Path
) -> None:
    image = _image(install_layout / "Applications")
    monkeypatch.setattr(appimage.shutil, "which", lambda _name: "/usr/bin/unsquashfs")
    with pytest.raises(
        RuntimeError, match="cursor_appimage_metadata_unreadable.*reinstall"
    ):
        appimage.read_appimage_version(
            image,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 1, "", "corrupt filesystem"
            ),
        )


def test_cursor_version_does_not_accept_vscode_version() -> None:
    with pytest.raises(ValueError, match="cursor_version_missing"):
        appimage.cursor_version('{"version":"1.105.0"}')


@pytest.mark.parametrize(
    "package_version,app_version",
    [
        ("1:3.18.2-1ubuntu1", "3.18.2"),
        ("3.18.2~beta1-1", "3.18.2-beta1"),
        ("3.18.2", "3.18.2"),
    ],
)
def test_debian_packaging_does_not_change_the_application_floor(
    monkeypatch,
    install_layout: Path,
    package_version: str,
    app_version: str,
) -> None:
    from yoke_contracts.session_control.surface_versions import (
        surface_version_meets_floor,
    )

    monkeypatch.setattr(
        apps.shutil,
        "which",
        lambda name: "/usr/bin/dpkg-query" if name == "dpkg-query" else None,
    )
    _, version = apps.read_linux_desktop_version(
        "cursor-desktop",
        home=install_layout,
        runner=lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, f"installed\t{package_version}", ""
        ),
    )
    assert version == app_version
    assert surface_version_meets_floor("cursor-desktop", version, "3.17.8")
    assert surface_version_meets_floor("cursor-desktop", version, "3.18.2") == (
        "beta" not in app_version
    )


def test_rpm_is_found_when_dpkg_tools_are_also_present(
    monkeypatch, install_layout: Path
) -> None:
    monkeypatch.setattr(
        apps.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("dpkg-query", "rpm") else None,
    )

    def query(command, **_kwargs):
        return (
            subprocess.CompletedProcess(command, 1, "", "no package")
            if "dpkg-query" in command[0]
            else subprocess.CompletedProcess(command, 0, "3.18.2", "")
        )

    assert apps.read_linux_desktop_version(
        "cursor-desktop", home=install_layout, runner=query
    ) == ("package", "3.18.2")
