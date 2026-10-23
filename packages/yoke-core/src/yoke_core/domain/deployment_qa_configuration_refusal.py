"""Tell a fixable QA configuration refusal apart from a real QA stage failure.

A saved plan the gate refuses (``QaPlanError``) is configuration an operator
can repair. One member's refusal holds that member: the stage records a
named blocker and keeps waiting on the others. The driver does not exit for
it, and the run stays executing at its QA stage. Any other error still fails
the stage.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from yoke_core.domain.qa_plan_management import QaPlanError


def configuration_blocker(
    exc: Exception,
    *,
    run_id: str,
    stage_name: str,
    member: int | None = None,
    item_refs: Callable[[Any], str] | None = None,
    label: str | None = None,
) -> str | None:
    """The waiting line for one subject's configuration refusal, or None."""
    if not isinstance(exc, QaPlanError):
        return None
    if label is None:
        label = f"member {item_refs(member)}" if member is not None else "run"
    return (
        f"{label}: qa_configuration_refused: {exc} "
        f"{label} stays held at stage {stage_name!r} while other members "
        "keep settling. Run "
        f"{run_id} stays executing and its recorded QA results are kept. "
        "Recovery: fix the named QA configuration, then re-drive the same "
        f"run with `yoke watch deploy -- {run_id}`."
    )


def qa_stage_error(exc: Exception, *, run_id: str, stage_name: str) -> tuple[int, str]:
    """The stage's answer for an error raised before any member is gated.

    A configuration refusal waits instead of stopping the driver. Any other
    error still fails the stage.
    """
    held = configuration_blocker(
        exc, run_id=run_id, stage_name=stage_name, label="run"
    )
    if held is not None:
        return -4, held
    return 1, str(exc)


__all__ = ["configuration_blocker", "qa_stage_error"]
