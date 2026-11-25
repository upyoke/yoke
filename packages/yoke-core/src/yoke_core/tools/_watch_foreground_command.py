"""Render shell commands for the shared watcher streaming output."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Sequence

from yoke_contracts import platform_process
from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.process_ancestry import process_basename
from yoke_contracts.uv_project import is_uv_project
from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS
from yoke_harness.native_windows.powershell import quote
from yoke_harness.native_windows.yoke_python import yoke_shim_process_info


def _anchor_directory(kind: str, start: Path | None = None) -> Path:
    """Return the checkout the printed command must enter.

    A subdirectory cwd embeds that sticky path in the minted line, and
    the watch adapter then binds a nested or mixed environment. Prefer
    the nearest uv-managed project within the git checkout; never cross
    a checkout boundary. Otherwise use the invocation directory. A merge
    removes the lane it lands, so ``merge`` anchors a linked worktree at
    its main checkout: a shell left in the deleted lane fails both lines.
    """
    here = (start or Path.cwd()).resolve()
    if kind == "merge":
        dirs = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--path-format=absolute",
             "--git-dir", "--git-common-dir"],
            capture_output=True, text=True, check=False,
        ).stdout.split()
        if len(dirs) == 2 and Path(dirs[0]).resolve() != Path(dirs[1]).resolve():
            return Path(dirs[1]).resolve().parent
    for candidate in [here, *here.parents]:
        if is_uv_project(candidate) or (candidate / ".git").exists():
            return candidate
    return here


def caller_uses_powershell() -> bool:
    """Read the nearest shell, ignoring launchers such as the yoke.cmd shim."""
    if os.name != "nt":
        return False
    for process in platform_process.ancestors(os.getpid()):
        name = process_basename(process.name)
        if name in {"powershell", "pwsh"}:
            return True
        if name in {"bash", "sh", "zsh", "fish", "dash", "ksh", "ash"}:
            return False
    return False


def _invocation(wrapper_module: str) -> tuple[list[str], str]:
    """Return the bound watcher argv and the module-only connection override."""
    connection = os.environ.get(ENV_OVERRIDE, "").strip()
    tokens = WATCH_CLI_TOKENS.get(wrapper_module)
    if tokens is None:
        return ["uv", "run", "--frozen", "python3", "-m", wrapper_module], connection
    argv = ["yoke"]
    if connection:
        argv.extend(["--env", connection])
    argv.extend(tokens)
    if os.environ.get(SOURCE_DEV_RUN_ROOT_ENV):
        argv = ["yoke", "dev", "run", "--", *argv]
    return argv, ""


def _bash_command(argv: list[str], connection: str) -> str:
    prefix = f"{ENV_OVERRIDE}={shlex.quote(connection)} " if connection else ""
    return f"{prefix}{shlex.join(argv)}"


def bash_tail(kind: str, wrapper_module: str, capture: Path) -> str:
    argv, connection = _invocation(wrapper_module)
    return (
        f"cd {shlex.quote(str(_anchor_directory(kind)))} && "
        f"{_bash_command([*argv, str(capture)], connection)}"
    )


def bound_wrapper_command(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str],
    powershell: bool = False,
) -> str:
    """Bind the checkout, connection and both captures to the watcher argv."""
    cwd = str(_anchor_directory(kind))
    argv, connection = _invocation(wrapper_module)
    argv.extend([
        *wrapper_options,
        "--raw-capture", str(raw_capture),
        "--progress-capture", str(progress_capture),
        "--", *wrapper_args,
    ])
    if powershell:
        return _powershell_command(cwd, argv, connection)
    trailing_space = "" if wrapper_args else " "
    return f"cd {shlex.quote(cwd)} && {_bash_command(argv, connection)}{trailing_space}"


def _powershell_command(cwd: str, argv: list[str], connection: str) -> str:
    # Windows PowerShell's native argument binder drops empty arguments and
    # embedded double quotes. The installed shim also adds cmd.exe parsing.
    # Start the executable directly with Windows argv and inherited streams.
    lookup = (
        f"$program=(Get-Command {quote(argv[0])} -CommandType Application "
        "-ErrorAction Stop).Source"
    )
    native = (
        "$info=[Diagnostics.ProcessStartInfo]::new(); $info.FileName=$program; "
        f"$info.Arguments={quote(subprocess.list2cmdline(argv[1:]))}"
    )
    if argv[0] == "yoke":
        shim = yoke_shim_process_info("$program", argv[1:])
        native = (
            "if ($program.EndsWith('.cmd', [StringComparison]::OrdinalIgnoreCase)) "
            f"{{ {shim} }} else {{ {native} }}"
        )
    env = (
        f"$info.EnvironmentVariables[{quote(ENV_OVERRIDE)}]={quote(connection)}; "
        if connection else ""
    )
    return (
        f"try {{ Set-Location -LiteralPath {quote(cwd)} -ErrorAction Stop }} "
        "catch { Write-Error ('watch_checkout_entry_failed: ' + $_ + "
        "'. Restore the checkout and print the watcher command again.') "
        "-ErrorAction Continue; exit 1 }; "
        "try { "
        f"{lookup}; "
        f"{native}; $info.UseShellExecute=$false; {env}"
        "$info.WorkingDirectory=(Get-Location).ProviderPath; "
        "$process=[Diagnostics.Process]::Start($info); "
        "$process.WaitForExit(); $code=$process.ExitCode; $process.Dispose() "
        "} catch { Write-Error ('watch_start_failed: ' + $_ + "
        "'. Check the printed checkout and repair the watcher executable on PATH.') "
        "-ErrorAction Continue; exit 1 }; exit $code"
    )


def raw_inspection(capture: Path, *, powershell: bool = False) -> str:
    if powershell:
        return f"Get-Content -LiteralPath {quote(str(capture))} -Tail 80 -Encoding UTF8"
    return f"tail -80 {shlex.quote(str(capture))}"
