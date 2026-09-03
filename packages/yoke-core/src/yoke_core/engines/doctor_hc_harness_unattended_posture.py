"""Doctor health check — every harness on this machine runs Yoke unattended.

Each harness a person opens reads its own persisted config to decide whether
to stop and ask before running a command, and each ships defaults that do.
The launcher install writes the unattended posture into all three, but a
machine installed before that pass existed, or one whose harness config has
since been rewritten, still asks — and the symptom is a stranger approving
every ``yoke`` call by hand, including the recovery commands Yoke tells them
to run when something breaks.

One record per harness the machine actually has. A harness that is not
installed is SKIP, not a pass: there is no posture to report.
"""

from __future__ import annotations

from yoke_contracts.harness_unattended_posture import (
    CLAUDE_FAMILY,
    CODEX_FAMILY,
    CURSOR_FAMILY,
    POSTURE_RECOVERY,
    managed_config_paths,
    posture_problems,
    read_posture_config,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

SLUG = "harness-unattended-posture"
TITLE = "Every installed harness runs yoke without approval prompts"


def hc_harness_unattended_posture(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-harness-unattended-posture: no harness prompts on yoke commands."""
    prompting: list[str] = []
    unattended: list[str] = []
    absent: list[str] = []
    for harness_id in (CLAUDE_FAMILY, CODEX_FAMILY, CURSOR_FAMILY):
        path = managed_config_paths()[harness_id]
        config, reason = read_posture_config(harness_id, path)
        if config is None:
            absent.append(reason)
            continue
        problems = posture_problems(harness_id, config)
        if problems:
            prompting.append(f"{harness_id} ({path}): {'; '.join(problems)}")
        else:
            unattended.append(harness_id)
    if prompting:
        rec.record(
            SLUG, TITLE, "FAIL",
            "A session you open in these harnesses asks before every yoke "
            "command.\n  " + "\n  ".join(prompting) + f"\n  {POSTURE_RECOVERY}",
        )
        return
    if not unattended:
        rec.record(
            SLUG, TITLE, "SKIP",
            "No managed harness is set up on this machine: " + "; ".join(absent),
        )
        return
    rec.record(
        SLUG, TITLE, "PASS",
        f"{', '.join(unattended)} run yoke unattended"
        + (f"; not installed here: {len(absent)}" if absent else ""),
    )


__all__ = ["SLUG", "TITLE", "hc_harness_unattended_posture"]
