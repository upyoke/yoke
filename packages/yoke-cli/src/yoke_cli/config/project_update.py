"""Refresh the current installed project after a machine CLI update."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from yoke_cli.project_install.files import ProjectInstallError, load_manifest


def refresh_current(yoke_bin: str) -> dict[str, Any]:
    """Use the updated executable, including when the machine is already current."""
    current = Path.cwd().resolve()
    root = next(
        (
            p
            for p in (current, *current.parents)
            if (p / ".yoke/install-manifest.json").is_file()
        ),
        None,
    )
    if root is None:
        return {"status": "not_installed"}
    return refresh_checkout(yoke_bin, root)


def refresh_checkout(
    yoke_bin: str,
    root: Path,
    *,
    run=None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Refresh one checkout through the installer's existing publish path."""
    manifest = load_manifest(root)
    if (manifest or {}).get("mode") == "source-link":
        return {"status": "source_dev", "recovery": "yoke dev setup"}
    try:
        result = (run or subprocess.run)(
            [yoke_bin, "project", "refresh", str(root), "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=600,
            **({"env": env} if env is not None else {}),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectInstallError(
            f"project_update_incomplete: project refresh could not finish for {root}. "
            "The CLI update is installed. Rerun yoke project refresh in that "
            "checkout to complete its operating layer."
        ) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2048:]
        raise ProjectInstallError(
            f"project_update_incomplete: project refresh failed for {root} "
            f"(exit {result.returncode}): {detail}. The CLI update is installed; "
            "resolve the named refusal, then rerun yoke project refresh."
        )
    try:
        report = json.loads(result.stdout)
        if not isinstance(report, dict):
            raise ValueError("report must be an object")
    except ValueError as exc:
        raise ProjectInstallError(
            "project_update_receipt_unreadable: refresh returned no readable "
            "completion report. Run yoke project refresh --json in the checkout "
            "and retain its completion receipt."
        ) from exc
    return {
        "status": "refreshed",
        "repo_root": str(root),
        "install_drift": report.get("install_drift"),
        "yoke_version": report.get("yoke_version"),
    }
