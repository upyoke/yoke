"""Converge expired relay leases without guessing native outcomes."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.db_helpers import instant_parameter

from datetime import datetime, timedelta

from typing import Any

from yoke_contracts.session_control.wake_delivery import (
    WAKE_DELIVERY_UNVERIFIED_RESULTS,
)
from yoke_core.domain.session_relay_types import WAKE_LEASE_SECONDS
from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS
from yoke_core.domain.session_relay_evidence import (
    redacted_evidence,
)
from yoke_core.domain.session_relay_storage import (
    clear_relay_batch_when_drained,
    marker,
)


_LEASE_EXPIRED_CODE = "relay_lease_expired"
RELAY_EXPIRY_ADAPTER_REVISION = "session-relay-expiry-v1"


def settle_expired_relay_leases(conn: Any, *, now: datetime | str) -> int:
    """Close unreported jobs at their own deadlines without guessing outcomes."""
    from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines

    settle_launch_deadlines(conn, now=now)
    p = marker(conn)
    rows = conn.execute(
        "SELECT DISTINCT relay_id,batch_id FROM session_launch_attempts "
        f"WHERE completed_at IS NULL AND started_at<={p}",
        (
            instant_parameter(
                conn, parse_instant(now) - timedelta(seconds=LAUNCH_LEASE_SECONDS)
            ),
        ),
    ).fetchall()
    changed = _settle_wakes(conn, now=now)
    for relay_id, batch_id in rows:
        changed += _settle_launches(conn, str(batch_id), now=now)
        clear_relay_batch_when_drained(
            conn, relay_id=str(relay_id), batch_id=str(batch_id)
        )
    conn.commit()
    return changed


def _settle_wakes(conn: Any, *, now: datetime | str) -> int:
    """Expire unreported wakes independently; reported natives keep custody."""
    p = marker(conn)
    unverified = tuple(sorted(WAKE_DELIVERY_UNVERIFIED_RESULTS))
    cursor = conn.execute(
        "UPDATE session_message_attempts SET completed_at="
        + p
        + ",result_code="
        + p
        + ",adapter_revision=COALESCE(adapter_revision,"
        + p
        + "),evidence="
        + p
        + " WHERE (attempt_kind='wake_relay' OR (attempt_kind='wake_broker' "
        "AND result_code='broker_native_claimed')) AND completed_at IS NULL "
        + f"AND started_at<={p} AND (result_code IS NULL OR result_code NOT IN ("
        + ",".join(p for _ in unverified)
        + "))",
        (
            instant_parameter(conn, parse_instant(now)),
            _LEASE_EXPIRED_CODE,
            RELAY_EXPIRY_ADAPTER_REVISION,
            redacted_evidence({"result_code": _LEASE_EXPIRED_CODE}),
            instant_parameter(
                conn, parse_instant(now) - timedelta(seconds=WAKE_LEASE_SECONDS)
            ),
            *unverified,
        ),
    )
    return max(0, cursor.rowcount)


def _settle_launches(conn: Any, batch_id: str, *, now: datetime | str) -> int:
    """Reconcile every launch this batch leased but never reported."""
    from yoke_core.domain.session_launch_execution import expire_launch_attempt
    from yoke_core.domain.session_launch_native_progress import native_attempt_pending
    from yoke_core.domain.session_launch_store import get_launch

    p = marker(conn)
    stranded = conn.execute(
        "SELECT launch_id,lease_id FROM session_launch_attempts "
        f"WHERE batch_id={p} AND completed_at IS NULL AND started_at<={p} "
        "ORDER BY started_at,launch_id",
        (
            batch_id,
            instant_parameter(
                conn, parse_instant(now) - timedelta(seconds=LAUNCH_LEASE_SECONDS)
            ),
        ),
    ).fetchall()
    changed = 0
    for launch_id, lease_id in stranded:
        launch = get_launch(conn, str(launch_id))
        if native_attempt_pending(conn, launch, now=now):
            continue
        expire_launch_attempt(
            conn,
            launch_id=str(launch_id),
            lease_id=str(lease_id),
            result_code=_LEASE_EXPIRED_CODE,
            now=now,
        )
        changed += 1
    return changed


__all__ = ["RELAY_EXPIRY_ADAPTER_REVISION", "settle_expired_relay_leases"]
