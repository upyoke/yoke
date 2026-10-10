"""Doctor-receipt line for product-wheel ``yoke status``.

Reads ``doctor.last_run.get`` when a control plane is already reachable.
Never runs Doctor inline. A missing receipt is ``health unverified`` and
does not flip ``ok``.

The summary names the receipt's own scope and warning count, so a narrow
``--only`` run is never read as whole-machine health, and a receipt that
recorded no scope says so rather than implying one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_cli.config.status_surface_policy import _control_plane_ready
from yoke_contracts.timestamps import InvalidInstant, parse_instant, utc_now

_UNVERIFIED = "health unverified — run yoke doctor run --quick"
_TIMEOUT_S = 8.0
_SCOPE_UNRECORDED = "scope not recorded (coverage unknown)"
_SCOPE_LABELS = {
    "quick": "quick scope",
    "full": "full scope",
    "only": "narrow --only run (not whole-machine)",
}


def attach_doctor(report: dict[str, Any]) -> dict[str, Any]:
    """Attach the latest doctor receipt summary without failing status."""
    summary = _UNVERIFIED
    if _control_plane_ready(report):
        summary = _summarize(_fetch_last_run(report))
    report["doctor"] = {"summary": summary}
    return report


def _fetch_last_run(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        project = report.get("project") or {}
        project_id = project.get("project_id") if isinstance(project, Mapping) else None
        payload: dict[str, Any] = {}
        if project_id is not None:
            payload["project"] = str(project_id)
        response = call_dispatcher(
            function_id="doctor.last_run.get",
            target=TargetRef(kind="global"),
            payload=payload,
            timeout_s=_TIMEOUT_S,
        )
        result = getattr(response, "result", None)
        return result if isinstance(result, Mapping) else None
    except Exception:
        return None


def _summarize(last_run: Mapping[str, Any] | None) -> str:
    if not last_run or last_run.get("never_run"):
        return _UNVERIFIED
    fail_count = int(last_run.get("fail_count") or 0)
    pass_count = int(last_run.get("pass_count") or 0)
    warn_count = int(last_run.get("warn_count") or 0)
    scope = _scope_label(last_run.get("scope"))
    try:
        age = _age_label(last_run.get("ran_at"))
    except InvalidInstant:
        return "health unverified — invalid receipt clock; run yoke doctor run --quick"
    return (
        f"{fail_count} FAIL / {pass_count} PASS / {warn_count} WARN, "
        f"{scope}, {age} — run yoke doctor run --quick"
    )


def _scope_label(scope: Any) -> str:
    """Name what the receipt actually covered, never implying more than it did."""
    text = str(scope or "").strip()
    if not text:
        return _SCOPE_UNRECORDED
    return _SCOPE_LABELS.get(text, f"{text} scope (not whole-machine)")


def _age_label(ran_at: datetime | str | None) -> str:
    if ran_at is None:
        return "unknown age"
    parsed = parse_instant(ran_at)
    seconds = max(0, int((utc_now() - parsed).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


__all__ = ["attach_doctor"]
