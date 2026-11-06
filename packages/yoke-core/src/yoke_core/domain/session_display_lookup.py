"""Read a display label through the configured control-plane transport."""


def session_identity_label(session_id: str) -> str:
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    try:
        response = call_dispatcher(
            function_id="sessions.list",
            target=TargetRef(kind="global"),
            payload={"session_id": session_id, "detail": "full"},
        )
    except Exception:
        return f"{session_id} (session label unavailable; retry sessions list)"
    if response.success:
        for row in (response.result or {}).get("rows", []):
            if row.get("session_id") == session_id:
                return f"{session_id} ({row.get('display_label') or 'session label unavailable'})"
    return f"{session_id} (session label unavailable; retry sessions list)"
