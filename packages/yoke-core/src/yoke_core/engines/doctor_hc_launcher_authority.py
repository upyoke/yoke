"""Doctor health check — login-shell yoke is the canonical launcher.

FAIL when a login shell resolves anything but the canonical shim, when
shadow installs sit on PATH, or when the interactive shell and the
login shell disagree. ``--fix`` runs the installer repair (repoint the
shim and quarantine shadows, never delete).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

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


SLUG = "launcher-authority"
TITLE = "Machine launcher resolves to canonical editable install"


def _login_shell_yoke() -> str:
    try:
        result = subprocess.run(
            ["/bin/zsh", "-lc", "command -v yoke"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def _resolve_checkout(args: DoctorArgs) -> Path | None:
    from yoke_core.engines import doctor_report as _base

    raw = _base._resolve_repo_root()
    if raw:
        return Path(raw)
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
            for token in command.replace("'", " ").replace('"', " ").split():
                if not (token.startswith("/") and token.endswith("/yoke")):
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
    canonical = canonical_shim_path()
    if args.fix:
        checkout = _resolve_checkout(args)
        if checkout is not None:
            try:
                converge_machine(checkout, stream=None)
            except Exception as exc:  # noqa: BLE001 — report, do not crash doctor
                rec.record(SLUG, TITLE, "FAIL", f"--fix repair failed: {exc}")
                return
    login = _login_shell_yoke()
    interactive = shutil.which("yoke") or ""
    shadows = enumerate_shadow_installs(canonical=canonical)
    problems: list[str] = []
    if not login:
        problems.append("login shell (`/bin/zsh -lc 'command -v yoke'`) resolved nothing")
    elif Path(login).resolve() != canonical.resolve():
        problems.append(
            f"login shell resolved {login!r}, not canonical {str(canonical)!r}"
        )
    if shadows:
        listed = ", ".join(f"{s.path} ({s.kind})" for s in shadows)
        problems.append(f"shadow installs on PATH: {listed}")
    if interactive and login and Path(interactive).resolve() != Path(login).resolve():
        problems.append(
            f"interactive yoke ({interactive}) differs from login-shell yoke ({login})"
        )
    checkout = _resolve_checkout(args)
    if checkout is not None:
        problems.extend(hook_config_yoke_problems(checkout, canonical))
    if problems:
        rec.record(
            SLUG, TITLE, "FAIL",
            "Machine launcher is not canonical.\n  " + "\n  ".join(problems)
            + "\n  Repair: python3 -m yoke_core.tools.install_yoke_launcher --repair"
            + "  (or `yoke doctor run --quick --fix`). Shadows are quarantined, never deleted.",
        )
        return
    rec.record(
        SLUG, TITLE, "PASS",
        f"Login-shell yoke is the canonical shim ({canonical}).",
    )


__all__ = ["SLUG", "TITLE", "hc_launcher_authority", "hook_config_yoke_problems"]
