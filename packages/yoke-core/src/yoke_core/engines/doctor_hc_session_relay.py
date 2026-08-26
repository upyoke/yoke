"""Doctor health check for the local macOS machine relay."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.credential_sources import (
    CREDENTIAL_KIND_TOKEN_FILE,
)
from yoke_contracts.session_control.function_ids import RELAY_FUNCTION_IDS
from yoke_core.domain.control_plane_transport import relay
from yoke_core.domain.session_relay_storage import marker, utc_now
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.session_relay_plist import relay_launchd_status


SLUG = "session-relay"
TITLE = "Machine relay login item, heartbeat, and API authorization"
_RELAY_LIST_FUNCTION_ID = RELAY_FUNCTION_IDS[0]


def _machine_id() -> str:
    try:
        return str(machine_config.load_config().get("machine_id") or "").strip()
    except Exception:
        return ""


def _token_reference_active() -> bool:
    """Check credential presence only; never read or expose the token value."""
    try:
        connection: Mapping[str, Any] = machine_config.active_connection()
    except Exception:
        return False
    source = connection.get("credential_source")
    if not isinstance(source, Mapping):
        return False
    if str(source.get("kind") or "") != CREDENTIAL_KIND_TOKEN_FILE:
        return False
    raw_path = source.get("path")
    return bool(
        isinstance(raw_path, str)
        and raw_path.strip()
        and Path(raw_path).expanduser().is_file()
    )


def _recent_relay(conn: Any, machine_id: str, now: str) -> tuple[str, str] | None:
    if conn is None:
        result = relay(
            _RELAY_LIST_FUNCTION_ID,
            {"state": "active", "limit": 500},
        )
        for row in result.get("relays") or []:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("machine_id") or "") != machine_id:
                continue
            if str(row.get("liveness") or "") != "connected":
                continue
            relay_id = str(row.get("relay_id") or "").strip()
            last_seen = str(row.get("last_seen_at") or "").strip()
            if relay_id and last_seen:
                return relay_id, last_seen
        return None
    p = marker(conn)
    row = conn.execute(
        "SELECT relay_id,last_seen_at FROM session_relays "
        f"WHERE machine_id={p} AND state<>'revoked' AND connected_until>{p} "
        "ORDER BY last_seen_at DESC LIMIT 1",
        (machine_id, now),
    ).fetchone()
    return (str(row[0]), str(row[1])) if row is not None else None


def hc_session_relay(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-session-relay: machine relay is installed and recently authenticated."""
    if sys.platform != "darwin":
        rec.record(
            SLUG,
            TITLE,
            NOT_APPLICABLE,
            "launchd relay support is macOS-only; systemd is not shipped",
        )
        return
    launchd = relay_launchd_status()
    problems: list[str] = []
    if not launchd.plist_present:
        problems.append(f"plist missing at {launchd.plist_path}")
    elif not launchd.plist_current:
        problems.append("plist does not match the current one-shot relay contract")
    if not launchd.loaded:
        problems.append("launchd login item is not loaded")
    machine_id = _machine_id()
    recent = _recent_relay(conn, machine_id, utc_now()) if machine_id else None
    if not machine_id:
        problems.append("machine config has no canonical machine id")
    elif recent is None:
        problems.append("control plane has no currently connected relay heartbeat")
    if not _token_reference_active():
        problems.append("active connection has no owner-only API token reference")
    if problems:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            "; ".join(problems)
            + ". Repair: `yoke relay install`, which loads the standing relay.",
        )
        return
    relay_id, last_seen = recent
    rec.record(
        SLUG,
        TITLE,
        "PASS",
        f"{relay_id} is loaded and authenticated; last seen {last_seen}.",
    )


__all__ = ["SLUG", "TITLE", "hc_session_relay"]
