"""Own and repair current, login, and SSH PATH state for Yoke and harnesses."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from yoke_cli.config.path_harness_clis import (
    HarnessCliResolution,
    managed_path_directories,
    resolve_harness_clis,
)

from yoke_cli.config.path_state_contract import (
    HARNESS_CLIS as HARNESS_CLIS,
    MANAGED_BEGIN,
    MANAGED_END,
    PATH_TOOLS,
    SUPPORTED_SHELLS,
    TOOLS as TOOLS,
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
    login_needs_fix: bool = False
    managed_path_dirs: tuple[str, ...] = ()
    harness_clis: tuple[HarnessCliResolution, ...] = ()


def render_managed_block(path_dirs: Sequence[str]) -> str:
    """The full managed block, BEGIN..END inclusive, with no trailing newline."""
    if isinstance(path_dirs, str) or not path_dirs:
        raise ValueError("managed PATH directories must be a non-empty sequence")
    managed_path = os.pathsep.join(dict.fromkeys(map(str, path_dirs)))
    return "\n".join(
        [
            MANAGED_BEGIN,
            "# Managed by Yoke — safe to delete this whole block.",
            f"_yoke_managed_path={shlex.quote(managed_path)}",
            '_yoke_existing_path="$PATH"',
            '_yoke_new_path=""',
            '_yoke_old_ifs="$IFS"',
            "IFS=:",
            "for _yoke_entry in $_yoke_managed_path $_yoke_existing_path; do",
            '  [ -n "$_yoke_entry" ] || continue',
            '  case ":$_yoke_new_path:" in',
            '    *":$_yoke_entry:"*) ;;',
            '    *) _yoke_new_path="${_yoke_new_path:+$_yoke_new_path:}$_yoke_entry" ;;',
            "  esac",
            "done",
            'IFS="$_yoke_old_ifs"',
            'PATH="$_yoke_new_path"',
            "export PATH",
            "unset _yoke_managed_path _yoke_existing_path _yoke_new_path",
            "unset _yoke_old_ifs _yoke_entry",
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


def apply_fix(startup_file: Path, path_dirs: Sequence[str]) -> bool:
    """Idempotently replace the product-managed block in one startup file."""
    existing = startup_file.read_text() if startup_file.exists() else ""
    body = _strip_managed_block(existing)
    if body and not body.endswith("\n"):
        body += "\n"
    new_text = body + render_managed_block(path_dirs) + "\n"
    if new_text == existing:
        return False
    startup_file.parent.mkdir(parents=True, exist_ok=True)
    startup_file.write_text(new_text)
    return True


def _probe_env_without_managed_paths(
    path_dirs: Sequence[str],
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a probe env without directories the managed block must add."""
    environ = dict(os.environ if env is None else env)
    managed = {entry.rstrip("/") for entry in path_dirs}
    path_value = environ.get("PATH", "")
    entries = path_value.split(os.pathsep) if path_value else ()
    kept = [entry for entry in entries if entry.rstrip("/") not in managed]
    environ["PATH"] = os.pathsep.join(kept) or os.defpath
    return environ


def _seeded_probe_home(
    shell: str, path_dirs: Sequence[str]
) -> tempfile.TemporaryDirectory[str]:
    """Isolated HOME/ZDOTDIR containing only the startup files Yoke writes."""
    home = tempfile.TemporaryDirectory(prefix="yoke-path-probe-")
    root = Path(home.name)
    block = render_managed_block(path_dirs) + "\n"
    default_startup_file(shell, root).write_text(block)
    ssh = default_ssh_startup_file(shell, root)
    if ssh is not None:
        ssh.write_text(block)
    return home


def _verify_shell(
    flag: str,
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
    managed_path_dirs: Sequence[str] | None = None,
) -> list[ToolResolution]:
    environ = dict(os.environ if env is None else env)
    path_dirs = tuple(managed_path_dirs or (tool_bin_dir(environ),))
    probe_env = _probe_env_without_managed_paths(path_dirs, environ)
    sh = shell or current_shell(probe_env)
    if sh not in SUPPORTED_SHELLS:
        sh = "zsh"
    shell_path = shutil.which(sh, path=probe_env.get("PATH")) or f"/bin/{sh}"
    script = "; ".join(f"command -v {tool} || true" for tool in PATH_TOOLS)
    with _seeded_probe_home(sh, path_dirs) as probe_home:
        probe_env["HOME"] = probe_home
        probe_env["ZDOTDIR"] = probe_home
        try:
            proc = subprocess.run(
                [shell_path, flag, script],
                capture_output=True,
                text=True,
                timeout=_VERIFY_TIMEOUT_S,
                env=probe_env,
            )
        except (OSError, subprocess.SubprocessError):
            return [ToolResolution(tool, None) for tool in PATH_TOOLS]
    resolved: dict[str, str] = {}
    for candidate in map(str.strip, proc.stdout.splitlines()):
        base = Path(candidate).name
        if candidate and base in PATH_TOOLS:
            resolved.setdefault(base, candidate)
    return [ToolResolution(tool, resolved.get(tool)) for tool in PATH_TOOLS]


def verify_fresh_login(
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
    managed_path_dirs: Sequence[str] | None = None,
) -> list[ToolResolution]:
    """Resolve tools in a login-interactive shell that sources Yoke's files only.

    Still uses ``-lic`` so the probe observes login-shell init order, including
    system files such as ``/etc/zprofile``. It does not source the operator's
    real rc files: HOME/ZDOTDIR are a temp tree seeded with the managed block.
    Combined with ``diagnose``'s static read of the real startup file, this
    proves the block works as a login PATH, not that other operator rc content
    is harmless.
    """
    return _verify_shell("-lic", shell, env=env, managed_path_dirs=managed_path_dirs)


def verify_ssh_command(
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
    managed_path_dirs: Sequence[str] | None = None,
) -> list[ToolResolution]:
    return _verify_shell("-c", shell, env=env, managed_path_dirs=managed_path_dirs)


def _resolves_required_tools(
    resolved: list[ToolResolution], required: Sequence[str]
) -> bool:
    by_name = {res.name: res.path for res in resolved}
    return all(bool(by_name.get(name)) for name in required)


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
    harness_clis = resolve_harness_clis(path_value)
    path_dirs = managed_path_directories(bindir, harness_clis)
    harness_paths = {
        resolution.executable: resolution.path for resolution in harness_clis
    }
    current_resolved = [
        ToolResolution(
            tool,
            harness_paths.get(tool) or shutil.which(tool, path=path_value),
        )
        for tool in PATH_TOOLS
    ]
    required_tools = (
        "yoke",
        "uv",
        *(resolution.executable for resolution in harness_clis if resolution.path),
    )
    preferred_yoke = _preferred_yoke_path(bindir)
    yoke_shadowed_by = _shadowing_yoke_path(current_resolved, bindir=bindir)

    startup = default_startup_file(shell, home_path)
    startup_text = startup.read_text() if startup.exists() else ""
    managed_block_present = MANAGED_BEGIN in startup_text
    future_adds_bin = bindir in startup_text
    desired_block = render_managed_block(path_dirs)
    future_resolved = verify_fresh_login(
        shell, env=environ, managed_path_dirs=path_dirs
    )
    future_yoke_shadowed_by = _shadowing_yoke_path(
        future_resolved,
        bindir=bindir,
    )
    future_ok = _resolves_required_tools(future_resolved, required_tools)
    login_needs_fix = (
        desired_block not in startup_text
        or not future_ok
        or bool(yoke_shadowed_by)
        or bool(future_yoke_shadowed_by)
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
        ssh_resolved = verify_ssh_command(
            shell, env=environ, managed_path_dirs=path_dirs
        )
        ssh_yoke_shadowed_by = _shadowing_yoke_path(ssh_resolved, bindir=bindir)
        ssh_ok = _resolves_required_tools(ssh_resolved, required_tools)
        ssh_needs_fix = (
            desired_block not in ssh_text or not ssh_ok or bool(ssh_yoke_shadowed_by)
        )
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
        needs_fix=login_needs_fix or ssh_needs_fix,
        ssh_startup_file=str(ssh_startup) if ssh_startup is not None else "",
        ssh_adds_bin=ssh_adds_bin,
        ssh_managed_block_present=ssh_managed_block_present,
        ssh_resolved=ssh_resolved,
        ssh_needs_fix=ssh_needs_fix,
        preferred_yoke_path=preferred_yoke,
        yoke_shadowed_by=yoke_shadowed_by,
        future_yoke_shadowed_by=future_yoke_shadowed_by,
        ssh_yoke_shadowed_by=ssh_yoke_shadowed_by,
        login_needs_fix=login_needs_fix,
        managed_path_dirs=path_dirs,
        harness_clis=harness_clis,
    )


__all__ = (
    "HARNESS_CLIS MANAGED_BEGIN MANAGED_END PATH_TOOLS SUPPORTED_SHELLS TOOLS "
    "HarnessCliResolution PathDiagnosis "
    "PathStateContract ToolResolution apply_fix current_shell default_startup_file "
    "default_ssh_startup_file diagnose render_managed_block "
    "resolve_path_state_contract startup_files_for_shell supported_startup_files "
    "tool_bin_dir verify_fresh_login verify_ssh_command"
).split()
