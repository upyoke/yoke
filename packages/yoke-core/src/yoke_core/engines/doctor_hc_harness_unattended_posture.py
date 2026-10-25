"""Doctor health check — every harness on this machine runs Yoke unattended.

Each harness a person opens reads its own persisted config to decide whether
to stop and ask before running a command, and each ships defaults that do.
The shared harness setup reconcile writes the unattended posture, but a
machine installed before reconciliation, or one whose harness config has
since been rewritten, still asks — and the symptom is a stranger approving
every ``yoke`` call by hand, including the recovery commands Yoke tells them
to run when something breaks.

A harness whose operator kept their own mode still passes when its
machine-wide allowlist names ``yoke`` (:mod:`yoke_contracts.harness_yoke_allow`).

One record per harness the machine actually has. A harness that is not
installed is N/A, not a pass: there is no posture to report.
"""

from __future__ import annotations

import os

from yoke_cli.config.path_harness_clis import resolve_harness_clis
from yoke_contracts.harness_unattended_posture import (
    CLAUDE_FAMILY,
    CODEX_FAMILY,
    CURSOR_FAMILY,
    POSTURE_RECOVERY,
    claude_settings_path,
    managed_config_paths,
    read_posture_config,
)
from yoke_contracts.harness_yoke_allow import (
    YOKE_COMMAND_ALLOW,
    yoke_allow_path,
    yoke_posture,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

SLUG = "harness-unattended-posture"
TITLE = "Every installed harness runs yoke without approval prompts"


def inspect_unattended_posture(
    harness_id: str, *, installed: bool, surface_id: str | None = None
) -> tuple[str, str]:
    """One harness's posture verdict: ``PASS``, ``FAIL`` or ``N/A`` and why.

    A harness with no config file and no CLI on PATH is not set up here, so
    it has no posture to report; one that is installed but unreadable fails.
    A mode the operator kept passes while the ``yoke`` allow entry stands;
    without that entry every ``yoke`` call asks, which fails.
    """
    cli_settings = harness_id == CLAUDE_FAMILY and surface_id == "claude-cli"
    if harness_id == CLAUDE_FAMILY and surface_id not in (
        None,
        "claude-cli",
        "claude-desktop",
    ):
        return "FAIL", (
            f"HARNESS_POSTURE_UNVERIFIED: {surface_id} has no verified posture "
            "reader. Report the surface to Yoke support before onboarding; "
            "changing Desktop settings cannot verify it."
        )
    path = (
        claude_settings_path() if cli_settings else managed_config_paths()[harness_id]
    )
    verdict = yoke_posture(harness_id, surface_id)
    if verdict is None:
        _config, reason = read_posture_config(harness_id, path)
        if path.exists() or installed:
            return "FAIL", f"HARNESS_POSTURE_UNVERIFIED: {harness_id}: {reason}"
        return "N/A", reason
    if verdict.blocking:
        return "FAIL", f"{harness_id}: {'; '.join(verdict.blocking)}"
    if verdict.kept:
        return "PASS", (
            f"{harness_id} (your mode kept: {'; '.join(verdict.kept)}; "
            f"{YOKE_COMMAND_ALLOW[harness_id]} allowed in "
            f"{yoke_allow_path(harness_id)})"
        )
    return "PASS", harness_id


def hc_harness_unattended_posture(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-harness-unattended-posture: no harness prompts on yoke commands."""
    prompting: list[str] = []
    unattended: list[str] = []
    absent: list[str] = []
    installed = {
        entry.harness_id
        for entry in resolve_harness_clis(os.environ.get("PATH"))
        if entry.path
    }
    for harness_id in (CLAUDE_FAMILY, CODEX_FAMILY, CURSOR_FAMILY):
        verdict, detail = inspect_unattended_posture(harness_id, installed=harness_id in installed)
        if verdict == "FAIL":
            prompting.append(detail)
        elif verdict == "PASS":
            unattended.append(detail)
        else:
            absent.append(detail)
    if prompting:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            "yoke still asks for approval: neither the unattended mode nor "
            "the yoke allow entry is set, or the config is unreadable.\n  "
            + "\n  ".join(prompting)
            + f"\n  {POSTURE_RECOVERY}",
        )
        return
    if not unattended:
        rec.record(
            SLUG,
            TITLE,
            "N/A",
            "No managed harness is set up on this machine: " + "; ".join(absent),
        )
        return
    rec.record(
        SLUG,
        TITLE,
        "PASS",
        f"{', '.join(unattended)} run yoke unattended"
        + (f"; not installed here: {len(absent)}" if absent else ""),
    )


__all__ = ["SLUG", "TITLE", "inspect_unattended_posture", "hc_harness_unattended_posture"]
