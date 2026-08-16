"""Doctor health check — login-shell yoke is the canonical launcher.

FAIL when a login shell resolves anything but the canonical shim, when
shadow installs sit on PATH, or when the interactive shell and the
login shell disagree. ``--fix`` runs the installer repair (repoint the
shim and quarantine shadows, never delete).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.install_yoke_launcher_sweep import (
    canonical_shim_path,
    converge_machine,
    enumerate_shadow_installs,
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


__all__ = ["SLUG", "TITLE", "hc_launcher_authority"]
