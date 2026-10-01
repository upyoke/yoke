"""Linux desktop inventory from installed metadata, never app execution."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Callable

from yoke_harness.linux_appimage_metadata import cursor_version, read_appimage_version

_PACKAGES = {"claude-desktop": "claude-desktop", "cursor-desktop": "cursor"}
_CURSOR_METADATA_PATHS = (
    Path("/usr/share/cursor/resources/app/package.json"),
    Path("/opt/cursor/resources/app/package.json"),
)


def _package_version(
    package: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str | None:
    dpkg = shutil.which("dpkg-query")
    rpm = shutil.which("rpm") if package == "cursor" else None
    for tool in (dpkg, rpm):
        if not tool:
            continue
        command = (
            [tool, "-W", "-f=${db:Status-Status}\t${Version}", package]
            if tool == dpkg
            else [tool, "-q", "--qf", "%{VERSION}", package]
        )
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        if completed.returncode:
            if completed.returncode == 1 and (
                tool == dpkg or "not installed" in (completed.stderr + completed.stdout)
            ):
                continue
            detail = (completed.stderr or "no output").strip()[:160]
            raise RuntimeError(
                f"desktop_package_query_failed: {detail}; repair the package database and retry"
            )
        if tool == dpkg:
            state, _, version = completed.stdout.strip().partition("\t")
            if state != "installed":
                continue
            # Debian's epoch/revision identify packaging, not the app's release.
            version = version.split(":", 1)[-1].rsplit("-", 1)[0].replace("~", "-")
        else:
            version = completed.stdout.strip()
        if not version:
            raise ValueError(
                "desktop_package_version_missing: reinstall the desktop package"
            )
        return version
    return None


def _cursor_appimages(home: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    executable = shutil.which("cursor")
    if executable:
        candidates.append(Path(executable).resolve())
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for directory in (data_home, *(Path(raw) for raw in data_dirs.split(":") if raw)):
        for entry in sorted((directory / "applications").glob("*[Cc]ursor*.desktop")):
            in_main_entry = False
            for line in entry.read_text(encoding="utf-8").splitlines():
                if line.startswith("["):
                    in_main_entry = line == "[Desktop Entry]"
                if in_main_entry and line.startswith("Exec="):
                    words = shlex.split(line[5:])
                    if words and Path(words[0]).is_absolute():
                        candidates.append(Path(words[0]))
                    break
    candidates.extend(sorted((home / "Applications").glob("*[Cc]ursor*.AppImage")))
    candidates.extend((home / ".local/bin/cursor", Path("/opt/cursor.AppImage")))
    return tuple(
        dict.fromkeys(
            candidate.resolve() for candidate in candidates if candidate.is_file()
        )
    )


def read_linux_desktop_version(
    surface: str,
    *,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    package = _PACKAGES[surface]
    version = _package_version(package, runner)
    if version:
        return "package", version
    if surface == "cursor-desktop":
        for metadata in _CURSOR_METADATA_PATHS:
            if metadata.is_file():
                return "file", cursor_version(metadata.read_text(encoding="utf-8"))
        for image in _cursor_appimages(home or Path.home()):
            with image.open("rb") as handle:
                header = handle.read(11)
            if image.suffix.lower() == ".appimage" or header[8:11] == b"AI\x02":
                return "file", read_appimage_version(image, runner=runner)
            metadata = image.parent / "resources/app/package.json"
            if metadata.is_file():
                return "file", cursor_version(metadata.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"desktop_app_missing: install {package}; portable Cursor must be on PATH, "
        "in ~/Applications, or registered by a cursor desktop entry"
    )
