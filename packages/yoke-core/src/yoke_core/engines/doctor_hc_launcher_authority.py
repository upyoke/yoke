"""Doctor health check — the native PATH resolves the canonical launcher.

FAIL when a login shell resolves anything but the canonical shim, when
shadow installs sit on PATH, or when the interactive shell and the
login shell disagree. ``--fix`` runs the installer repair (repoint the
shim and quarantine shadows, never delete).
"""

from __future__ import annotations

from yoke_contracts.runtime_ports.install_advice import get_install_advice

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from yoke_contracts.hook_shell_command import hook_command_source

from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.install_yoke_launcher_sweep import (
    canonical_shim_path,
    converge_machine,
    enumerate_shadow_installs,
)

_HOOK_CONFIG_RELATIVE = (
    Path(".claude/settings.json"),
    Path(".cursor/hooks.json"),
    Path(".codex/hooks.json"),
)


_WINDOWS = sys.platform == "win32"

SLUG = "launcher-authority"
TITLE = "Machine launcher resolves to the released CLI"


def _machine_launcher_env() -> dict[str, str]:
    """Exclude only the verified source runner's temporary interpreter path."""
    env = dict(os.environ)
    env.pop("YOKE_SOURCE_DEV", None)
    source_root = env.get(SOURCE_DEV_RUN_ROOT_ENV)
    if not source_root:
        return env
    source_venv = Path(source_root).resolve() / ".venv"
    if Path(sys.prefix).resolve() != source_venv:
        return env
    temporary_bin = source_venv / "bin"
    env["PATH"] = (
        os.pathsep.join(
            part
            for part in env.get("PATH", "").split(os.pathsep)
            if part and Path(part).resolve() != temporary_bin
        )
        or os.defpath
    )
    return env


def _login_shell_yoke() -> str:
    env = _machine_launcher_env()
    tool_dir = str(canonical_shim_path().parent)
    env["PATH"] = (
        os.pathsep.join(
            part
            for part in env.get("PATH", "").split(os.pathsep)
            if part.rstrip("/") != tool_dir.rstrip("/")
        )
        or os.defpath
    )
    try:
        result = subprocess.run(
            [os.environ.get("SHELL") or "/bin/sh", "-lc", "command -v yoke"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def _resolve_checkout(args: DoctorArgs) -> Path | None:
    from yoke_core.engines import doctor_report as _base

    raw = _base._resolve_repo_root()
    if raw:
        return Path(raw)
    return None


def _release_problem(launcher: str, env: dict[str, str]) -> str | None:
    try:
        result = subprocess.run(
            [launcher, "--version"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"released_cli_unavailable: version probe failed: {exc}"
    version = (result.stdout or "").strip()
    if result.returncode or not version or version == "source":
        detail = (result.stderr or version or "no version returned").strip()
        return f"released_cli_required: {detail}"
    return None


def _command_strings(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        command = payload.get("command")
        if isinstance(command, str) and command.strip():
            found.append(command)
        for value in payload.values():
            found.extend(_command_strings(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_command_strings(item))
    return found


def hook_config_yoke_problems(root: Path, canonical: Path) -> list[str]:
    """FAIL when a hook command names a non-canonical absolute ``yoke``."""
    problems: list[str] = []
    try:
        canonical_resolved = canonical.resolve()
    except OSError:
        canonical_resolved = canonical
    for relative in _HOOK_CONFIG_RELATIVE:
        path = root / relative
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for command in _command_strings(payload):
            for token in (
                hook_command_source(command).replace("'", " ").replace('"', " ").split()
            ):
                if not (
                    Path(token).is_absolute()
                    and Path(token).name in {"yoke", "yoke.cmd", "yoke.exe"}
                ):
                    continue
                try:
                    resolved = Path(token).expanduser().resolve()
                except OSError:
                    continue
                if resolved != canonical_resolved:
                    problems.append(
                        f"{relative} command names {token}, not canonical {canonical}"
                    )
    return problems


def hc_launcher_authority(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-launcher-authority: login-shell yoke is the canonical shim."""
    from yoke_contracts.runtime_ports.launcher_path_doctor import get_launcher_path_doctor

    path_doctor = get_launcher_path_doctor()

    machine_env = _machine_launcher_env()
    checkout = _resolve_checkout(args)
    if args.fix:
        try:
            if _WINDOWS:
                path_doctor.update_shell(env=machine_env)
            elif checkout is not None:
                converge_machine(checkout, stream=None)
        except Exception as exc:  # noqa: BLE001 — report, do not crash doctor
            rec.record(SLUG, TITLE, "FAIL", f"--fix repair failed: {exc}")
            return

    diagnosis = path_doctor.diagnose(env=machine_env)
    if _WINDOWS:
        canonical = Path(diagnosis.preferred_yoke_path)
        login = next(
            (tool.path for tool in diagnosis.future_resolved if tool.name == "yoke"),
            None,
        )
        interactive = next(
            (tool.path for tool in diagnosis.current_resolved if tool.name == "yoke"),
            None,
        )
        # The Windows installer ships an extensionless POSIX shim alongside
        # yoke.cmd. The native PATH diagnosis identifies actual shadowing.
        shadows = []
    else:
        canonical = canonical_shim_path()
        login = _login_shell_yoke()
        interactive = shutil.which("yoke", path=machine_env.get("PATH"))
        shadows = enumerate_shadow_installs(canonical=canonical, env=machine_env)

    problems: list[str] = []
    for context in diagnosis.contexts:
        if context["needs_fix"]:
            problems.append(
                f"{context['shell']} {context['context']}: {context['reason']}; "
                + context["recovery"]
            )
    path_context = "fresh Windows PATH" if _WINDOWS else "fresh login shell"
    if not login:
        problems.append(
            f"{path_context} resolved no yoke; run `yoke path fix --yes`, then open a new terminal"
        )
    elif Path(login).resolve() != canonical.resolve():
        problems.append(
            f"{path_context} resolved {login!r}, not canonical {str(canonical)!r}"
        )
    else:
        release_problem = _release_problem(login, machine_env)
        if release_problem:
            problems.append(release_problem)
    if shadows:
        listed = ", ".join(f"{s.path} ({s.kind})" for s in shadows)
        problems.append(f"shadow installs on PATH: {listed}")
    if interactive and login and Path(interactive).resolve() != Path(login).resolve():
        problems.append(
            f"interactive yoke ({interactive}) differs from login-shell yoke ({login})"
        )
    if checkout is not None:
        problems.extend(hook_config_yoke_problems(checkout, canonical))
    if problems:
        if _WINDOWS:
            recovery = (
                "Repair the installed launcher with `yoke update`, then run "
                "`yoke path fix --yes` and open a new terminal."
            )
        else:
            try:
                recovery = f"Install the release: {get_install_advice().install_command()}."
            except get_install_advice().InstallOriginUnavailable as exc:
                recovery = f"{exc}; then install the release."
            recovery += (
                " Then repair: python3 -m yoke_core.tools.install_yoke_launcher --repair"
                " (or `yoke doctor run --quick --fix`). Shadows are quarantined, never deleted."
            )
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            "Machine launcher is not canonical.\n  "
            + "\n  ".join(problems)
            + f"\n  {recovery}",
        )
        return
    rec.record(
        SLUG,
        TITLE,
        "PASS",
        f"The {path_context} resolves the canonical shim ({canonical}).",
    )


__all__ = ["SLUG", "TITLE", "hc_launcher_authority", "hook_config_yoke_problems"]
