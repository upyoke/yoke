"""Refuse relay work when a source checkout is newer than its server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_cli.transport import control_plane_payload, source_build_skew
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.runtime_identity import SOURCE_VERSION_LABEL
from yoke_contracts.session_control.function_ids import RELAY_LIST_FUNCTION_ID
from yoke_contracts.session_control.relay_health import (
    RELAY_NEWER_THAN_SERVER,
    RELAY_NEWER_THAN_SERVER_RECOVERY,
)
from yoke_harness.session_relay_health import (
    clear_relay_run_refusal,
    observe_relay_health,
    record_relay_run_refusal,
)


Dispatcher = Callable[..., Any]


@dataclass(frozen=True)
class RelayBuildRefusal:
    local_revision: str
    server_revision: str
    ahead_by: int

    @property
    def message(self) -> str:
        return (
            f"{RELAY_NEWER_THAN_SERVER}: relay revision {self.local_revision} "
            f"is {self.ahead_by} commit(s) ahead of server revision "
            f"{self.server_revision}; recovery: {RELAY_NEWER_THAN_SERVER_RECOVERY}"
        )


def refusal_from_observation(
    observed: control_plane_payload.ObservedServerBuild,
) -> RelayBuildRefusal | None:
    comparison = observed.comparison
    if comparison is None or comparison.relationship != source_build_skew.AHEAD:
        return None
    local_revision = str(comparison.local_head or "").strip()
    server_revision = str(observed.name or comparison.server_build or "").strip()
    if not local_revision or not server_revision:
        return None
    return RelayBuildRefusal(
        local_revision=local_revision,
        server_revision=server_revision,
        ahead_by=max(1, int(comparison.ahead_by or 0)),
    )


def refusal_from_health(health: object) -> RelayBuildRefusal | None:
    if not isinstance(health, dict):
        return None
    value = health.get("run_refusal")
    if not isinstance(value, dict) or value.get("reason") != RELAY_NEWER_THAN_SERVER:
        return None
    local_revision = str(value.get("local_revision") or "").strip()
    server_revision = str(value.get("server_revision") or "").strip()
    if not local_revision or not server_revision:
        return None
    return RelayBuildRefusal(
        local_revision=local_revision,
        server_revision=server_revision,
        ahead_by=max(1, int(value.get("ahead_by") or 0)),
    )


def refresh_relay_build_compatibility(
    dispatcher: Dispatcher,
    *,
    state_dir: Path | None,
    timeout_s: int,
) -> RelayBuildRefusal | None:
    """Probe a stable read so the existing HTTPS handshake can compare builds."""
    pinned_release = local_handshake_version() or SOURCE_VERSION_LABEL
    recorded_refusal = observe_relay_health(state_dir).get("run_refusal")
    if isinstance(recorded_refusal, dict) and (
        recorded_refusal.get("pinned_release") != pinned_release
    ):
        clear_relay_run_refusal(state_dir)
    try:
        dispatcher(
            function_id=RELAY_LIST_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"limit": 1},
            timeout_s=timeout_s,
        )
    except Exception:
        # The ordinary claim/report path owns transport failure reporting. A
        # failed probe must not erase a previously grounded build refusal.
        return None
    observed = control_plane_payload.current_server_build()
    refusal = refusal_from_observation(observed)
    if refusal is None:
        comparison = observed.comparison
        if (
            comparison is not None
            and comparison.relationship != source_build_skew.UNKNOWN
        ):
            clear_relay_run_refusal(state_dir)
        return None
    record_relay_run_refusal(
        state_dir,
        pinned_release=pinned_release,
        local_revision=refusal.local_revision,
        server_revision=refusal.server_revision,
        ahead_by=refusal.ahead_by,
    )
    return refusal


__all__ = [
    "RelayBuildRefusal",
    "refresh_relay_build_compatibility",
    "refusal_from_health",
    "refusal_from_observation",
]
