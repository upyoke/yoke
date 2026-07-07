"""Diagnose and repair PATH visibility for uv / uvx / yoke.

After a fresh ``curl … | install`` run, the product binaries are linked into
the uv tool bin directory (``$XDG_BIN_HOME`` or ``~/.local/bin``). They resolve
inside the installer's own process because the shim prepends that directory to
PATH, but a brand-new login shell will not find them unless a shell startup
file puts the directory on PATH. This module reports both facts — resolution in
the current process and resolution as the next login shell would see it — and
repairs the future shell by writing ONE idempotent managed block bounded by
markers an operator (and the EC2-Mac wipe recipe) can grep and delete.

The module holds no UI. The ``yoke path`` CLI and the first-run onboarding
wizard both drive these functions; the wizard renders the preview and collects
consent before calling :func:`apply_fix`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Markers MUST contain the literal "BEGIN YOKE MANAGED PATH" /
# "END YOKE MANAGED PATH" substrings: the EC2-Mac reset recipe strips the
# block by grepping for exactly those, and idempotent re-application keys on
# them. Do not reword without updating that recipe.
MANAGED_BEGIN = "# >>> BEGIN YOKE MANAGED PATH >>>"
MANAGED_END = "# <<< END YOKE MANAGED PATH <<<"

TOOLS = ("uv", "uvx", "yoke")
_VERIFY_TIMEOUT_S = 10


@dataclass(frozen=True)
class ToolResolution:
    """How one tool resolves: its absolute path, or ``None`` if unresolved."""

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


def tool_bin_dir(env: dict | None = None) -> str:
    environ = os.environ if env is None else env
    xdg = environ.get("XDG_BIN_HOME")
    if xdg:
        return xdg
    home = environ.get("HOME") or str(Path.home())
    return str(Path(home) / ".local" / "bin")


def current_shell(env: dict | None = None) -> str:
    environ = os.environ if env is None else env
    name = Path(environ.get("SHELL") or "").name
    return name or "zsh"


def default_startup_file(shell: str, home: Path) -> Path:
    if shell == "zsh":
        return home / ".zprofile"
    if shell == "bash":
        return home / ".bash_profile"
    return home / ".profile"


def default_ssh_startup_file(shell: str, home: Path) -> Path | None:
    if shell == "zsh":
        return home / ".zshenv"
    if shell == "bash":
        return home / ".bashrc"
    return None


def render_managed_block(tool_bin_dir: str) -> str:
    """The full managed block, BEGIN..END inclusive, with no trailing newline."""
    return "\n".join(
        [
            MANAGED_BEGIN,
            "# Managed by Yoke — safe to delete this whole block.",
            'case ":$PATH:" in',
            f'  *":{tool_bin_dir}:"*) ;;',
            f'  *) export PATH="{tool_bin_dir}:$PATH" ;;',
            "esac",
            MANAGED_END,
        ]
    )


def _strip_managed_block(text: str) -> str:
    """Return ``text`` with any MANAGED_BEGIN..MANAGED_END region removed."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == MANAGED_BEGIN:
            skipping = True
            continue
        if stripped == MANAGED_END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)


def apply_fix(startup_file: Path, tool_bin_dir: str) -> bool:
    """Idempotently write the managed block into ``startup_file``.

    Removes any prior managed block, preserves all other content, appends one
    freshly rendered block, and creates the file (and parents) if missing.
    Returns ``True`` iff the file content changed — a second consecutive call
    with the same args returns ``False`` and leaves the bytes identical.
    """
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


def _probe_env_without_installer_path(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env for login-shell probes without the installer PATH shim."""
    environ = dict(os.environ if env is None else env)
    bindir = tool_bin_dir(environ).rstrip("/")
    path_value = environ.get("PATH", "")
    kept: list[str] = []
    for entry in path_value.split(os.pathsep) if path_value else []:
        normalized = entry.rstrip("/")
        if normalized == bindir or normalized.startswith(f"{bindir}/"):
            continue
        kept.append(entry)
    environ["PATH"] = os.pathsep.join(kept) or os.defpath
    return environ


def verify_fresh_login(
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[ToolResolution]:
    """Resolve the tools as a fresh login+interactive shell would. Never raises.

    Spawns ``<shell> -lic 'command -v …'`` so the user's startup files run; on
    any failure (missing shell, timeout) returns ``None`` for each tool.
    """
    probe_env = _probe_env_without_installer_path(env)
    sh = shell or current_shell(probe_env)
    if sh not in ("zsh", "bash"):
        sh = "zsh"
    shell_path = shutil.which(sh, path=probe_env.get("PATH")) or f"/bin/{sh}"
    script = "; ".join(f"command -v {tool} || true" for tool in TOOLS)
    try:
        proc = subprocess.run(
            [shell_path, "-lic", script],
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT_S,
            env=probe_env,
        )
    except (OSError, subprocess.SubprocessError):
        return [ToolResolution(tool, None) for tool in TOOLS]
    resolved: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        base = Path(candidate).name
        if base in TOOLS and base not in resolved:
            resolved[base] = candidate
    return [ToolResolution(tool, resolved.get(tool)) for tool in TOOLS]


def verify_ssh_command(
    shell: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[ToolResolution]:
    """Resolve tools as an SSH one-shot command would.

    macOS Remote Login runs commands like ``ssh host 'yoke status'`` through a
    non-login, non-interactive user shell. For zsh that reads ``~/.zshenv`` but
    not ``~/.zprofile``. This probe mirrors that shape so installer PATH repair
    covers the exact SSH workflow used by cold-start test Macs.
    """
    probe_env = _probe_env_without_installer_path(env)
    sh = shell or current_shell(probe_env)
    if sh not in ("zsh", "bash"):
        sh = "zsh"
    shell_path = shutil.which(sh, path=probe_env.get("PATH")) or f"/bin/{sh}"
    script = "; ".join(f"command -v {tool} || true" for tool in TOOLS)
    try:
        proc = subprocess.run(
            [shell_path, "-c", script],
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT_S,
            env=probe_env,
        )
    except (OSError, subprocess.SubprocessError):
        return [ToolResolution(tool, None) for tool in TOOLS]
    resolved: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        base = Path(candidate).name
        if base in TOOLS and base not in resolved:
            resolved[base] = candidate
    return [ToolResolution(tool, resolved.get(tool)) for tool in TOOLS]


def _resolves_runtime_tools(resolved: list[ToolResolution]) -> bool:
    by_name = {res.name: res.path for res in resolved}
    return bool(by_name.get("yoke")) and bool(by_name.get("uv"))


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

    startup = default_startup_file(shell, home_path)
    startup_text = startup.read_text() if startup.exists() else ""
    managed_block_present = MANAGED_BEGIN in startup_text
    future_adds_bin = bindir in startup_text

    future_resolved = verify_fresh_login(shell, env=environ)
    future_ok = _resolves_runtime_tools(future_resolved)
    if not future_ok and (managed_block_present or future_adds_bin):
        # The fresh-login probe could not run here (e.g. a sandbox without an
        # interactive shell); trust the static signal that the startup file
        # already puts the bin dir on PATH rather than over-reporting needs_fix.
        future_ok = True
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
        ssh_ok = _resolves_runtime_tools(ssh_resolved)
        if not ssh_ok and (ssh_managed_block_present or ssh_adds_bin):
            ssh_ok = True
        ssh_needs_fix = not ssh_ok

    return PathDiagnosis(
        current_shell=shell,
        tool_bin_dir=bindir,
        current_on_path=current_on_path,
        current_resolved=current_resolved,
        startup_file=str(startup),
        future_adds_bin=future_adds_bin,
        managed_block_present=managed_block_present,
        future_resolved=future_resolved,
        needs_fix=(not future_ok) or ssh_needs_fix,
        ssh_startup_file=str(ssh_startup) if ssh_startup is not None else "",
        ssh_adds_bin=ssh_adds_bin,
        ssh_managed_block_present=ssh_managed_block_present,
        ssh_resolved=ssh_resolved,
        ssh_needs_fix=ssh_needs_fix,
    )


__all__ = [
    "MANAGED_BEGIN",
    "MANAGED_END",
    "TOOLS",
    "PathDiagnosis",
    "ToolResolution",
    "apply_fix",
    "current_shell",
    "default_startup_file",
    "default_ssh_startup_file",
    "diagnose",
    "render_managed_block",
    "tool_bin_dir",
    "verify_fresh_login",
    "verify_ssh_command",
]
