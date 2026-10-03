"""Converge the Windows user's WSL distro lifetime without losing settings."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

MINIMUM_WSL_VERSION = (2, 5, 4)
RECOVERY = "Run wsl --update from Windows, then rerun yoke wsl setup in Ubuntu."
CONFIG_RECOVERY = (
    "Repair the Windows user profile .wslconfig and its permissions, "
    "then rerun yoke wsl setup."
)
INTEROP_RECOVERY = (
    "Enable Windows interop/PATH in /etc/wsl.conf, restart WSL, "
    "then rerun yoke wsl setup."
)


def _decode(output: bytes) -> str:
    encoding = (
        "utf-16"
        if output.startswith((b"\xff\xfe", b"\xfe\xff"))
        else ("utf-16-le" if b"\x00" in output else "utf-8-sig")
    )
    try:
        return output.decode(encoding).strip()
    except UnicodeError as exc:
        raise RuntimeError(f"wsl_windows_output_invalid: {exc}. {RECOVERY}") from exc


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"wsl_windows_command_unavailable: {command[0]}: {exc}. {INTEROP_RECOVERY}"
        ) from exc
    if result.returncode:
        raise RuntimeError(
            f"wsl_windows_command_failed: {command[0]} exited {result.returncode}; "
            f"{_decode(result.stderr or result.stdout)}. {RECOVERY}"
        )
    return _decode(result.stdout)


def _windows_command(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(
            f"wsl_windows_interop_unavailable: {name} is not on PATH. {INTEROP_RECOVERY}"
        )
    return resolved


def _check_version() -> None:
    text = _run([_windows_command("wsl.exe"), "--version"])
    # The label is localized; the first line always identifies WSL itself.
    match = re.search(
        r"(\d+)\.(\d+)\.(\d+)(?:\.\d+)?\s*$", text.splitlines()[0] if text else ""
    )
    if not match:
        raise RuntimeError(
            f"wsl_version_unreadable: cannot read the WSL version. {RECOVERY}"
        )
    version = tuple(int(value) for value in match.groups())
    if version < MINIMUM_WSL_VERSION:
        minimum = ".".join(str(value) for value in MINIMUM_WSL_VERSION)
        raise RuntimeError(
            f"wsl_lifetime_version_unsupported: WSL {'.'.join(match.groups())}; "
            f"instanceIdleTimeout requires WSL {minimum} or newer. {RECOVERY}"
        )


def _config_path() -> Path:
    profile = _run(
        [
            _windows_command("powershell.exe"),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "[Environment]::GetFolderPath('UserProfile')",
        ]
    )
    if not re.fullmatch(r"[A-Za-z]:[\\/][^\r\n]+", profile):
        raise RuntimeError(
            "wsl_windows_profile_unavailable: Windows did not return an absolute user profile. "
            "Restore Windows user profile access, then rerun yoke wsl setup."
        )
    converted = _run(["wslpath", "-u", profile])
    path = Path(converted)
    if not path.is_absolute() or not path.is_dir():
        raise RuntimeError(
            "wsl_windows_profile_unmounted: Windows user profile is not mounted in WSL. "
            "Restore Windows drive mounts in /etc/wsl.conf, restart WSL, "
            "then rerun yoke wsl setup."
        )
    return path / ".wslconfig"


def enabled_config(text: str) -> str:
    """Validate INI, change only the lifetime value, retain formatting elsewhere."""
    parser = configparser.ConfigParser(
        interpolation=None, inline_comment_prefixes=("#", ";")
    )
    try:
        parser.read_string(text)
        sections = [
            section for section in parser.sections() if section.lower() == "general"
        ]
        if len(sections) > 1:
            raise ValueError("duplicate general sections")
    except (configparser.Error, ValueError) as exc:
        raise RuntimeError(
            f"wsl_lifetime_config_invalid: {exc}. {CONFIG_RECOVERY}"
        ) from exc
    if sections and parser.get(sections[0], "instanceIdleTimeout", fallback="") == "-1":
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    entry = f"instanceIdleTimeout=-1{newline}"
    lines = text.splitlines(keepends=True)
    in_general = False
    for index, line in enumerate(lines):
        section = re.match(r"^\s*\[([^]]+)\]", line)
        if section:
            if in_general:
                lines.insert(index, entry)
                return "".join(lines)
            in_general = section.group(1).lower() == "general"
        elif in_general:
            setting = re.match(
                r"^(\s*instanceIdleTimeout\s*[:=]\s*)[^#;\r\n]*(.*)$", line, re.I
            )
            if setting:
                ending = newline if line.endswith(("\n", "\r")) else ""
                comment = setting.group(2).rstrip()
                suffix = f" {comment}" if comment else ""
                lines[index] = f"{setting.group(1)}-1{suffix}{ending}"
                return "".join(lines)
    separator = newline if text and not text.endswith(("\n", "\r")) else ""
    header = "" if sections else f"{newline}[general]{newline}"
    return text + separator + header + entry


def _enable(path: Path) -> bool:
    temporary = None
    try:
        if path.is_symlink():
            raise RuntimeError(
                f"wsl_lifetime_config_symlink: {path}. {CONFIG_RECOVERY}"
            )
        raw = path.read_bytes() if path.exists() else b""
        encoding = (
            "utf-16-le"
            if raw.startswith(b"\xff\xfe")
            else ("utf-16-be" if raw.startswith(b"\xfe\xff") else "utf-8")
        )
        text = raw.decode(encoding)
        bom = "\ufeff" if text.startswith("\ufeff") else ""
        updated = bom + enabled_config(text.removeprefix(bom) if bom else text)
        if updated == text:
            return False
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(updated.encode(encoding))
            file.flush()
            os.fsync(file.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
        if path.read_bytes() != updated.encode(encoding):
            raise RuntimeError(
                f"wsl_lifetime_config_unverified: {path}. {CONFIG_RECOVERY}"
            )
        return True
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"wsl_lifetime_config_write_failed: {path}: {exc}. {CONFIG_RECOVERY}"
        ) from exc
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def setup(*, emit=print) -> bool:
    _check_version()
    path = _config_path()
    changed = _enable(path)
    if changed:
        emit(
            f"Changed {path}: [general] instanceIdleTimeout=-1; WSL2 idle shutdown is disabled for this Windows user. A WSL restart is required."
        )
    else:
        emit(
            f"WSL2 idle shutdown is already disabled in {path}. If changed since WSL last started, run wsl --shutdown from Windows and reopen Ubuntu."
        )
    return changed
