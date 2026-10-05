"""Due fleet reports and the cross-report memory of displayed rows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence, TextIO

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
    PROJECT_POLICY_CAPABILITY,
)
from yoke_core.domain.fleet_delta_snapshot import (
    FleetReadError,
    FleetSnapshot,
    STEERING_REPORT_FUNCTION,
)
from yoke_core.domain.fleet_delta_disappearances import (
    ShownRow,
    disappeared_lines,
    shown_rows,
)
from yoke_core.domain.steering_fleet_report_render import REPORT_END

PROJECT_POLICY_FUNCTION = "projects.capability_settings.get"
STEERING_REPORT_INTERVAL_KEY = "steering_report_interval_minutes"


def _response_result(response: Any, function_id: str) -> dict[str, Any]:
    """Unwrap a registered read or raise a named fleet-read failure."""
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = (
            f"{error.code}: {error.message}" if error is not None else "unknown error"
        )
        raise FleetReadError(function_id, detail)
    return dict(getattr(response, "result", None) or {})


def _report_interval_minutes(
    project: str,
    *,
    call: Callable[[str, dict[str, Any]], Any],
) -> int:
    result = _response_result(
        call(
            PROJECT_POLICY_FUNCTION,
            {"project": project, "cap_type": PROJECT_POLICY_CAPABILITY},
        ),
        PROJECT_POLICY_FUNCTION,
    )
    try:
        settings = json.loads(str(result.get("settings_json") or "{}"))
    except (TypeError, ValueError) as exc:
        raise FleetReadError(
            PROJECT_POLICY_FUNCTION,
            f"project {project} returned invalid project-policy JSON",
        ) from exc
    if not isinstance(settings, Mapping):
        raise FleetReadError(
            PROJECT_POLICY_FUNCTION,
            f"project {project} project-policy must be a JSON object",
        )
    try:
        minutes = int(
            settings.get(
                STEERING_REPORT_INTERVAL_KEY,
                DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
            )
        )
    except (TypeError, ValueError):
        minutes = DEFAULT_STEERING_REPORT_INTERVAL_MINUTES
    return max(1, minutes)


@dataclass
class ReportState:
    checked_at: datetime | None = None
    fingerprint: str = ""
    rows: dict[tuple[str, str, str, str], ShownRow] = field(default_factory=dict)


def append_steering_reports(
    projects: Sequence[str],
    *,
    observed_at: datetime,
    stream: TextIO,
    call: Callable[[str, dict[str, Any]], Any],
    state: ReportState,
    report: Mapping[str, Any] | None = None,
    snapshot: FleetSnapshot | None = None,
) -> None:
    """Check all held scopes when due, including quiet and timer-only passes."""
    try:
        interval = min(
            _report_interval_minutes(project, call=call) for project in projects
        )
        if state.checked_at is not None and observed_at - state.checked_at < timedelta(
            minutes=interval
        ):
            return
        # Retain every held document seat; compose only on a due pass.
        result = (
            report
            if report is not None
            else _response_result(
                call(STEERING_REPORT_FUNCTION, {}), STEERING_REPORT_FUNCTION
            )
        )
        fingerprint = str(result.get("fingerprint") or "").strip()
        payload = (
            str(result.get("digest") or "").strip()
            or str(result.get("body") or "").strip()
        )
        if not fingerprint or not payload:
            raise FleetReadError(
                STEERING_REPORT_FUNCTION,
                "held-scope response omitted fingerprint or body",
            )
        rows = shown_rows(result, digest=bool(result.get("digest")))
        removed = disappeared_lines(state.rows, rows, result, snapshot)
        state.checked_at = observed_at
        if state.fingerprint != fingerprint or removed:
            if removed:
                explanation = "\n".join(["no longer listed:", *removed])
                payload = (
                    payload.removesuffix(REPORT_END).rstrip()
                    + "\n\n"
                    + explanation
                    + "\n"
                    + REPORT_END
                    if payload.endswith(REPORT_END)
                    else payload + "\n" + explanation
                )
            state.fingerprint = fingerprint
            _write(stream, payload)
            state.rows = rows
    except FleetReadError as failure:
        _write(
            stream,
            f"fleet ERROR steering report unavailable via {failure.function_id}: "
            f"{failure.detail}; check `yoke steering report get`, then keep "
            "the fleet watch armed for the next probe pass",
        )


def _write(stream: TextIO, line: str) -> None:
    stream.write(f"{line}\n")
    stream.flush()
