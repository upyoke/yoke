"""Run the harness posture pass from onboarding, reporting instead of raising.

Onboarding writes this posture as one named step among many, so a harness
config it cannot write leaves a machine that still prompts — not a broken
install. The failure is reported into the onboarding report and the run
continues.
"""

from __future__ import annotations

import io
from typing import List


def apply_reported() -> List[str]:
    """Write the posture into every detected harness; never raise."""
    from yoke_core.tools.install_harness_unattended_posture import (
        configure_harness_unattended_posture,
    )

    try:
        return configure_harness_unattended_posture(stream=io.StringIO())
    except Exception as exc:  # noqa: BLE001 — reported, never fatal
        return [f"harness posture was not written: {exc}"]


__all__ = ["apply_reported"]
