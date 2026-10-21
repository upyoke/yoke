"""Tell a fixable QA configuration refusal apart from a real QA stage failure.

A saved plan the gate refuses (``QaPlanError``) is configuration an operator
can repair. Failing the run for it would throw away every member's passed QA,
so the stage answers a distinct code that stops the driver and leaves the run
executing at its QA stage. Any other error still fails the stage.
"""

from __future__ import annotations

from yoke_core.domain.qa_plan_management import QaPlanError

#: Stops the driver without recording the run failed; the run stays executing.
QA_CONFIGURATION_REFUSED = -6


def qa_stage_error(exc: Exception, *, run_id: str, stage_name: str) -> tuple[int, str]:
    """The stage's answer for an error raised while gating its subjects."""
    if not isinstance(exc, QaPlanError):
        return 1, str(exc)
    return QA_CONFIGURATION_REFUSED, (
        f"qa_configuration_refused: {exc} Run {run_id} stays executing at stage "
        f"{stage_name!r} and was not failed; its recorded QA results are kept. "
        "Recovery: fix the named QA configuration, then re-drive the same run "
        f"with `yoke watch deploy -- {run_id}`."
    )


__all__ = ["QA_CONFIGURATION_REFUSED", "qa_stage_error"]
