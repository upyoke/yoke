"""Attach the caller's server-owned session and item state to status."""

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_state_fields import session_state_columns


def attach_session_state(report):
    from yoke_cli.config.status_surface_policy import _control_plane_ready
    from yoke_cli.transport.dispatcher import call_dispatcher
    from yoke_cli.transport.dispatcher import _resolve_session_id

    if not _control_plane_ready(report):
        return report
    session_id = _resolve_session_id()
    if not session_id:
        return report
    response = call_dispatcher(
        function_id="sessions.list", target=TargetRef(kind="global"),
        payload={"session_id": session_id, "detail": "full"}, timeout_s=8,
    )
    if not response.success:
        report["session"] = {"error": response.error.model_dump(mode="json")}
        return report
    rows = (response.result or {}).get("rows") or []
    if rows:
        row = rows[0]
        report["session"] = {
            "session_id": session_id,
            **session_state_columns(row),
            "current_item": row.get("current_item"),
        }
        if row.get("current_item"):
            item = call_dispatcher(
                function_id="items.get.run",
                target=TargetRef(kind="item", public_ref=row["current_item"]),
                payload={"fields": ["stage", "home_section", "next_actor", "progress"]},
                timeout_s=8,
            )
            report["item_state"] = ((item.result or {}).get("fields") if item.success
                                    else {"error": item.error.model_dump(mode="json")})
    return report
