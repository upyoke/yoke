"""Own and repair current, login, and SSH PATH state for uv, uvx, and yoke."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from yoke_cli.config.path_state_contract import (
    MANAGED_BEGIN,
    MANAGED_END,
    SUPPORTED_SHELLS,
    TOOLS,
    PathStateContract as PathStateContract,
    current_shell,
    default_ssh_startup_file,
    default_startup_file,
    resolve_path_state_contract as resolve_path_state_contract,
    startup_files_for_shell as startup_files_for_shell,
    supported_startup_files as supported_startup_files,
    tool_bin_dir,
)


_VERIFY_TIMEOUT_S = 10


@dataclass(frozen=True)
class ToolResolution:
    name: str
    path: str | None


@dataclass(frozen=True)
class PathDiagnosis:
    current_shell: str
    tool_bin_dir: str
    current_on_path: bool
    current_resolved: list[ToolResolution]
    startup_file: str
    future_adds_bin: bool
    managed_block_present: bool
    future_resolved: list[ToolResolution]
    needs_fix: bool
    ssh_startup_file: str = ""
    ssh_adds_bin: bool = False
    ssh_managed_block_present: bool = False
    ssh_resolved: list[ToolResolution] = field(default_factory=list)
    ssh_needs_fix: bool = False
    preferred_yoke_path: str = ""
    yoke_shadowed_by: str = ""
    future_yoke_shadowed_by: str = ""
    ssh_yoke_shadowed_by: str = ""


def render_managed_block(tool_bin_dir: str) -> str:
    """The full managed block, BEGIN..END inclusive, with no trailing newline."""
    return "\n".join(
        [
            MANAGED_BEGIN,
            "# Managed by Yoke — safe to delete this whole block.",
            f'_yoke_bin_dir="{tool_bin_dir}"',
            'if [ -n "${ZSH_VERSION:-}" ]; then',
            '  path=("${(@)path:#$_yoke_bin_dir}")',
            '  path=("$_yoke_bin_dir" $path)',
            "else",
            '  _yoke_old_path="$PATH"',
            '  PATH="$_yoke_bin_dir"',
            '  _yoke_old_ifs="$IFS"',
            "  IFS=:",
            "  for _yoke_entry in $_yoke_old_path; do",
            '    [ "$_yoke_entry" = "$_yoke_bin_dir" ] && continue',
            '    PATH="$PATH:$_yoke_entry"',
            "  done",
            '  IFS="$_yoke_old_ifs"',
            "  unset _yoke_old_path _yoke_old_ifs _yoke_entry",
            "fi",
            "export PATH",
            "unset _yoke_bin_dir",
            MANAGED_END,
        ]
    )


def _strip_managed_block(text: str) -> str:
    """Return ``text`` with any MANAGED_BEGIN..MANAGED_END region removed."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped in {MANAGED_BEGIN, MANAGED_END}:
            skipping = stripped == MANAGED_BEGIN
        elif not skipping:
            out.append(line)
    return "".join(out)


def apply_fix(startup_file: Path, tool_bin_dir: str) -> bool:
    """Idempotently replace the product-managed block in one startup file."""
    existing = startup_file.read_text() if startup_file.exists() else ""
    body = _strip_managed_block(existing)
    if body and not body.endswith("\n"):
        body += "\n"
    new_text = body + render_managed_block(tool_bin_dir) + "\n"
    if new_text == existing:
        return False
    startup_file.parent.mkdir(parents=True, exist_ok=True)
    startup_file.write_text(new_text)
    return True


def _probe_env_without_installer_path(
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return an env for login-shell probes without the installer PATH shim."""
    environ = dict(os.environ if env is None else env)
    bindir = tool_bin_dir(environ).rstrip("/")
    path_value = environ.get("PATH", "")
    entries = path_value.split(os.pathsep) if path_value else ()
    kept = [
        entry
        for entry in entries
        if entry.rstrip("/") != bindir
        and not entry.rstrip("/").startswith(f"{bindir}/")
    ]
    environ["PATH"] = os.pathsep.join(kept) or os.defpath
    return environ


def _verify_shell(
    flag: str,
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[ToolResolution]:
    probe_env = _probe_env_without_installer_path(env)
    sh = shell or current_shell(probe_env)
    if sh not in SUPPORTED_SHELLS:
        sh = "zsh"
    shell_path = shutil.which(sh, path=probe_env.get("PATH")) or f"/bin/{sh}"
    script = "; ".join(f"command -v {tool} || true" for tool in TOOLS)
    try:
        proc = subprocess.run(
            [shell_path, flag, script],
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT_S,
            env=probe_env,
        )
    except (OSError, subprocess.SubprocessError):
        return [ToolResolution(tool, None) for tool in TOOLS]
    resolved: dict[str, str] = {}
    for candidate in map(str.strip, proc.stdout.splitlines()):
        base = Path(candidate).name
        if candidate and base in TOOLS:
            resolved.setdefault(base, candidate)
    return [ToolResolution(tool, resolved.get(tool)) for tool in TOOLS]


def verify_fresh_login(
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[ToolResolution]:
    return _verify_shell("-lic", shell, env=env)


def verify_ssh_command(
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[ToolResolution]:
    return _verify_shell("-c", shell, env=env)


def _resolves_runtime_tools(resolved: list[ToolResolution]) -> bool:
    by_name = {res.name: res.path for res in resolved}
    return bool(by_name.get("yoke")) and bool(by_name.get("uv"))


def _preferred_yoke_path(bindir: str) -> str:
    return str(Path(bindir) / "yoke")


def _shadowing_yoke_path(resolved: list[ToolResolution], *, bindir: str) -> str:
    """Return the path that wins over the installed Yoke shim, or ``""``."""
    preferred = _preferred_yoke_path(bindir)
    if not Path(preferred).exists():
        return ""
    by_name = {res.name: res.path for res in resolved}
    winner = by_name.get("yoke")
    shadowed = winner and Path(winner).expanduser() != Path(preferred).expanduser()
    return winner if shadowed else ""


def diagnose(*, env: dict | None = None, home: Path | None = None) -> PathDiagnosis:
    environ = dict(os.environ if env is None else env)
    home_path = home or Path(environ.get("HOME") or str(Path.home()))
    bindir = tool_bin_dir(environ)
    shell = current_shell(environ)
    path_value = environ.get("PATH", "")
    path_entries = path_value.split(os.pathsep) if path_value else []
    current_on_path = bindir in path_entries
    current_resolved = [
        ToolResolution(tool, shutil.which(tool, path=path_value or None))
        for tool in TOOLS
    ]
    preferred_yoke = _preferred_yoke_path(bindir)
    yoke_shadowed_by = _shadowing_yoke_path(current_resolved, bindir=bindir)

    startup = default_startup_file(shell, home_path)
    startup_text = startup.read_text() if startup.exists() else ""
    managed_block_present = MANAGED_BEGIN in startup_text
    future_adds_bin = bindir in startup_text

    future_resolved = verify_fresh_login(shell, env=environ)
    future_yoke_shadowed_by = _shadowing_yoke_path(
        future_resolved,
        bindir=bindir,
    )
    future_ok = (
        _resolves_runtime_tools(future_resolved)
        or future_adds_bin
        or managed_block_present
    )
    ssh_startup = default_ssh_startup_file(shell, home_path)
    ssh_adds_bin = False
    ssh_managed_block_present = False
    ssh_resolved: list[ToolResolution] = []
    ssh_needs_fix = False
    if ssh_startup is not None:
        ssh_text = ssh_startup.read_text() if ssh_startup.exists() else ""
        ssh_adds_bin = bindir in ssh_text
        ssh_managed_block_present = MANAGED_BEGIN in ssh_text
        ssh_resolved = verify_ssh_command(shell, env=environ)
        ssh_yoke_shadowed_by = _shadowing_yoke_path(ssh_resolved, bindir=bindir)
        ssh_ok = (
            _resolves_runtime_tools(ssh_resolved)
            or ssh_adds_bin
            or ssh_managed_block_present
        )
        ssh_needs_fix = (not ssh_ok) or bool(ssh_yoke_shadowed_by)
    else:
        ssh_yoke_shadowed_by = ""

    return PathDiagnosis(
        current_shell=shell,
        tool_bin_dir=bindir,
        current_on_path=current_on_path,
        current_resolved=current_resolved,
        startup_file=str(startup),
        future_adds_bin=future_adds_bin,
        managed_block_present=managed_block_present,
        future_resolved=future_resolved,
        needs_fix=(
            (not future_ok)
            or bool(yoke_shadowed_by)
            or bool(future_yoke_shadowed_by)
            or ssh_needs_fix
        ),
        ssh_startup_file=str(ssh_startup) if ssh_startup is not None else "",
        ssh_adds_bin=ssh_adds_bin,
        ssh_managed_block_present=ssh_managed_block_present,
        ssh_resolved=ssh_resolved,
        ssh_needs_fix=ssh_needs_fix,
        preferred_yoke_path=preferred_yoke,
        yoke_shadowed_by=yoke_shadowed_by,
        future_yoke_shadowed_by=future_yoke_shadowed_by,
        ssh_yoke_shadowed_by=ssh_yoke_shadowed_by,
    )


__all__ = (
    "MANAGED_BEGIN MANAGED_END SUPPORTED_SHELLS TOOLS PathDiagnosis "
    "PathStateContract ToolResolution apply_fix current_shell default_startup_file "
    "default_ssh_startup_file diagnose render_managed_block "
    "resolve_path_state_contract startup_files_for_shell supported_startup_files "
    "tool_bin_dir verify_fresh_login verify_ssh_command"
).split()
