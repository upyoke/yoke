"""Supersede a QA case whose declared host baseline was wrong.

A case's host baseline is part of its obligation scope: a pass from one
baseline proves nothing about another, so supersession normally refuses a
replacement at a different baseline. When the baseline itself was the
defect (a case that needs Yoke on its host declared ``fresh-host``), the
operator records the corrected case at the right baseline and supersedes
the broken one with ``--corrects-baseline``. The link is stored on the
broken row, so every later reader of the link (the done gate's graph walk,
successor validation, source retirement) compares the same scope without
the baseline. The broken row and its evidence stay as history.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Column on the superseded row recording that its link corrects the baseline.
CORRECTS_BASELINE = "supersession_corrects_baseline"


def ignores_baseline(broken: Mapping[str, Any]) -> bool:
    """Whether *broken*'s supersession link was recorded as a baseline fix."""
    return bool(broken.get(CORRECTS_BASELINE))


def baseline_correction_refusal(
    broken: Mapping[str, Any], corrected: Mapping[str, Any], *, source: str
) -> str:
    """Why this pair cannot be a baseline correction, or ``""`` when it can."""
    if source != "operator":
        return (
            "--corrects-baseline records an operator's judgment that the "
            "superseded case declared the wrong host baseline; rerun with "
            "--source operator and the operator's rationale"
        )
    old = str(broken.get("host_baseline") or "")
    new = str(corrected.get("host_baseline") or "")
    if not new:
        return (
            f"requirement {corrected['id']} names no host baseline, so it "
            "corrects none; record the corrected case with --host-baseline NAME"
        )
    if old == new:
        return (
            f"both requirements start from host baseline {new!r}, so there is "
            "no baseline to correct; drop --corrects-baseline"
        )
    return ""


__all__ = ["CORRECTS_BASELINE", "baseline_correction_refusal", "ignores_baseline"]
