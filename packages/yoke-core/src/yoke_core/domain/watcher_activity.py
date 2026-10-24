"""A bound watch wrapper reports work independently of session liveness."""

from pathlib import Path

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.api import service_client_structured_api_adapter as structured_api


def refresh_watcher_activity(session_id: str, *, progress_capture: Path) -> bool:
    """Send a pulse only from the loop running the bound watcher command.

    The capture binding already belongs to this wrapper. Failure is visible in
    that same progress capture so a successful command cannot conceal lost
    activity reporting. Ordinary session liveness never calls this path.
    """
    try:
        response = structured_api.call_dispatcher(
            function_id="sessions.watcher_activity",
            target=TargetRef(kind="global"),
            payload={},
            actor=ActorContext(session_id=session_id),
            intent="running watcher activity",
        )
        if response.success:
            return True
        reason = str(response.error.message if response.error else "unknown refusal")
    except Exception as exc:  # noqa: BLE001 - command continues with visible lost evidence
        reason = str(exc)
    message = compose_refusal(
        f"watcher_activity_unavailable: {reason}",
        recovery=(
            "Ask the control-plane operator to restore watcher activity reporting "
            "and align the CLI/server serving versions; inspect this capture before "
            "acting on an idle alarm. The watched command continues"
        ),
    )
    with progress_capture.open("a", encoding="utf-8") as capture:
        capture.write(f"# {message}\n")
    return False
