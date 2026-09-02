"""Record a late apply step's outcome on an already-written apply report.

The wizard writes the operator's board art after ``build_report`` returns and
after the durable report has been finished, so that step's real outcome — the
commit that hands over a clean checkout, or the failure that stopped it — has
to be written back onto the step the write plan already named. Without it the
receipt reports a step done that had not yet run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_report


def complete_report_path(
    path: str | Path,
    *,
    action: str,
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    """Mark a late apply step done on an already-written report."""
    writer = _writer(path)
    step_id = _step_id_for_action(writer.payload, action)
    if step_id:
        writer.step_outcome(step_id, detail)
    return writer.summary()


def fail_report_path(
    path: str | Path,
    error: BaseException,
    *,
    action: str | None = None,
) -> dict[str, Any]:
    """Mark an already-written apply report failed after a late apply step."""
    writer = _writer(path)
    writer.fail(error, step_id=_step_id_for_action(writer.payload, action))
    return writer.summary()


def _writer(path: str | Path) -> onboard_apply_report.ApplyReportWriter:
    report_path = Path(path).expanduser()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return onboard_apply_report.ApplyReportWriter(report_path, payload)


def _step_id_for_action(
    payload: Mapping[str, Any],
    action: str | None,
) -> str | None:
    if not action:
        return None
    for raw in payload.get("steps") or []:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("action") == action:
            return str(raw.get("step_id") or "")
    return None


__all__ = ["complete_report_path", "fail_report_path"]
