"""Launch state, identity, delivery, and recovery labels."""

from collections.abc import Mapping
from typing import Any

from yoke_cli.commands.adapters.session_control_human_output import (
    EMPTY_VALUE,
    humanize,
)


def _launch_status(launch: Mapping[str, Any]) -> str:
    state = humanize(launch.get("state"))
    result = humanize(launch.get("result_code"))
    return f"{state} ({result})" if result != EMPTY_VALUE else state


def _launch_identity(launch: Mapping[str, Any]) -> str:
    state = str(launch.get("identity_correlation") or "unknown")
    labels = {
        "matched": "matched",
        "mismatch": "mismatch",
        "awaiting_registration": "awaiting registration",
        "registration_failed": "registration failed",
        "native_unreported": "native identity not reported",
        "correlation_failed": (f"failed ({humanize(launch.get('result_code'))})"),
        "unavailable": "unavailable",
        "pending": "waiting for native session",
        "unknown": "status unavailable",
    }
    return labels.get(state, humanize(state))


def _instruction_delivery(launch: Mapping[str, Any]) -> str:
    state = str(launch.get("instruction_delivery") or "unknown")
    return {
        "delivered": "delivered",
        "not_delivered": "not delivered",
        "pending": "pending",
        "awaiting_acknowledgement": "awaiting recipient acknowledgement",
        "unknown": "status unavailable",
    }.get(state, humanize(state))


def _launch_recovery(launch: Mapping[str, Any]) -> str | None:
    if launch.get("result_code") == "launch_acknowledgement_missing":
        return (
            "Inspect the registered session and its message receipt; resolve "
            "any active work claim before retrying this launch."
        )
    if launch.get("result_code") == "model_combo_unsupported":
        return (
            "Choose a supported model, reasoning effort, and context window; "
            "then create a new launch. The rejected launch never falls back."
        )
    if (
        launch.get("instruction_delivery") != "not_delivered"
        or launch.get("state") != "outcome_unknown"
    ):
        return None
    launch_id = str(launch.get("launch_id") or "LAUNCH-ID")
    native = str(launch.get("native_session_id") or "").strip()
    command = f"yoke session-control launch reconcile {launch_id}"
    if native:
        return f"Reconcile before retry: {command} --observed-native-id {native}"
    return (
        "Find the native session ID, then reconcile before retry: "
        f"{command} --observed-native-id ID"
    )
