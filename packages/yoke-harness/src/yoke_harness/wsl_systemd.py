"""Enable WSL systemd without replacing unrelated distribution settings."""

from __future__ import annotations

import configparser
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from yoke_harness.system_privileges import command_authority
from yoke_harness.wsl import is_wsl, systemd_running
from yoke_harness import wsl_lifetime

CONFIG_PATH = Path("/etc/wsl.conf")
RESTART = "Save your work, run wsl --shutdown from Windows, then reopen Ubuntu."
RECOVERY = "Rerun yoke wsl setup in an Ubuntu terminal with administrator access."


def _config(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=("#", ";"),
    )
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise RuntimeError(
            f"wsl_config_invalid: {exc}. Repair /etc/wsl.conf, then rerun yoke wsl setup."
        ) from exc
    return parser


def _enabled(text: str) -> bool:
    return _config(text).get("boot", "systemd", fallback="").lower() == "true"


def enabled_config(text: str) -> str:
    """Change only the boot flag, retaining comments and other settings."""
    parser = _config(text)
    if _enabled(text):
        return text
    lines = text.splitlines(keepends=True)
    if not parser.has_section("boot"):
        return (
            text
            + ("\n" if text and not text.endswith("\n") else "")
            + "\n[boot]\nsystemd=true\n"
        )
    in_boot = False
    for index, line in enumerate(lines):
        section = re.match(r"^\s*\[([^]]+)\]", line)
        if section:
            if in_boot:
                lines.insert(index, "systemd=true\n")
                return "".join(lines)
            in_boot = section.group(1) == "boot"
        elif in_boot and re.match(r"^\s*systemd\s*[:=]", line, re.IGNORECASE):
            lines[index] = "systemd=true\n"
            return "".join(lines)
    return text + ("\n" if text and not text.endswith("\n") else "") + "systemd=true\n"


def _read(path: Path) -> str:
    try:
        if path.is_symlink():
            raise RuntimeError(
                "wsl_config_symlink: /etc/wsl.conf must be a regular file. "
                "Replace the symlink with its intended configuration, then rerun yoke wsl setup."
            )
        return path.read_text() if path.exists() else ""
    except OSError as exc:
        raise RuntimeError(f"wsl_config_unreadable: {exc}. {RECOVERY}") from exc


def _enable(path: Path = CONFIG_PATH) -> None:
    """Called once under OS authority; reread before writing atomically."""
    text = _read(path)
    updated = enabled_config(text)
    if updated == text:
        return
    temporary = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(updated)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    except OSError as exc:
        raise RuntimeError(f"wsl_config_write_failed: {exc}. {RECOVERY}") from exc
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _setup_systemd(*, emit=print) -> str:
    if not is_wsl():
        return "not_wsl"
    try:
        running = systemd_running()
    except OSError as exc:
        raise RuntimeError(
            f"wsl_pid1_unreadable: {exc}; restore /proc access and rerun yoke wsl setup."
        ) from exc
    if running:
        emit("WSL systemd is already running as PID 1.")
        return "already_running"
    if not _enabled(_read(CONFIG_PATH)):
        prefix, interactive = command_authority(
            "wsl_systemd_authority_unavailable: Cannot enable /etc/wsl.conf: "
            "no root access, passwordless sudo, or interactive terminal with sudo "
            f"is available. {RECOVERY}"
        )
        if not prefix:
            _enable()
        else:
            try:
                result = subprocess.run(
                    [
                        *prefix,
                        sys.executable,
                        "-m",
                        "yoke_harness.wsl_systemd",
                        "--enable",
                    ],
                    text=True,
                    capture_output=not interactive,
                )
            except OSError as exc:
                raise RuntimeError(
                    f"wsl_systemd_enable_failed: {exc}. {RECOVERY}"
                ) from exc
            if result.returncode:
                raise RuntimeError(
                    f"wsl_systemd_enable_failed: {result.stderr or result.stdout or result.returncode}. {RECOVERY}"
                )
        if not _enabled(_read(CONFIG_PATH)):
            raise RuntimeError(
                f"wsl_systemd_enable_unverified: /etc/wsl.conf is still disabled. {RECOVERY}"
            )
    emit("WSL systemd is enabled in /etc/wsl.conf; a distribution restart is required.")
    emit(RESTART)
    return "restart_required"


def setup(*, emit=print) -> str:
    if not is_wsl():
        return "not_wsl"
    result = _setup_systemd(emit=emit)
    changed = wsl_lifetime.setup(emit=emit)
    if changed and result == "already_running":
        emit(RESTART)
        return "restart_required"
    return result


def main() -> int:
    try:
        if sys.argv[1:] != ["--enable"] or not is_wsl():
            raise RuntimeError(
                "wsl_systemd_writer_refused: use yoke wsl setup inside WSL."
            )
        _enable()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
