"""Doctor-receipt line for product-wheel ``yoke status``.

Reads ``doctor.last_run.get`` when a control plane is already reachable.
Never runs Doctor inline. A missing receipt is ``health unverified`` and
does not flip ``ok``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_cli.config.status_surface_policy import _control_plane_ready

_UNVERIFIED = "health unverified — run yoke doctor run --quick"
_TIMEOUT_S = 8.0


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
    age = _age_label(str(last_run.get("ran_at") or ""))
    return f"{fail_count} FAIL / {pass_count} PASS, {age} — run yoke doctor run --quick"


def _age_label(ran_at: str) -> str:
    if not ran_at:
        return "unknown age"
    try:
        parsed = datetime.fromisoformat(ran_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown age"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
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
