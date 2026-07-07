"""HC-work-claim-status-mismatch: suspicious active item claims."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import yoke_core.engines.doctor_report as _base
from yoke_core.domain import db_backend
from yoke_core.domain.runtime_settings import get_int
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-work-claim-status-mismatch"
_HC_DESC = "Active item work-claims held on a role-mismatched status"
_REQUIRED_TABLES = ("work_claims", "items", "harness_sessions")
_DEFAULT_STALE_TTL_MINUTES = 20
_IDEA_DRAFT_MODES = ("idea", "refine")
_LIST_PREVIEW = 20

_SCAN_SQL = """
SELECT
    wc.id              AS claim_id,
    wc.item_id         AS item_id,
    wc.session_id      AS session_id,
    i.status           AS item_status,
    hs.mode            AS session_mode,
    hs.ended_at        AS session_ended_at,
    hs.last_heartbeat  AS session_last_heartbeat
FROM work_claims wc
JOIN items i ON i.id = wc.item_id
LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id
WHERE wc.released_at IS NULL
  AND wc.target_kind = 'item'
  AND wc.item_id IS NOT NULL
  AND i.status IN ('release', 'idea')
"""


def _heartbeat_age_minutes(value: Optional[str], now: datetime) -> Optional[float]:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 60.0


def hc_work_claim_status_mismatch(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Report leaked item claims that disagree with the item's status role."""
    for table in _REQUIRED_TABLES:
        if not _base._table_exists(conn, table):
            rec.record(_HC_NAME, _HC_DESC, "PASS",
                       f"{table} table missing — skipping")
            return

    ttl_minutes = get_int("session_stale_ttl_minutes", _DEFAULT_STALE_TTL_MINUTES)
    now = datetime.now(timezone.utc)

    try:
        rows = conn.execute(_SCAN_SQL).fetchall()
    except db_backend.database_error_types(conn) as exc:
        rec.record(_HC_NAME, _HC_DESC, "PASS",
                   f"required columns missing — skipping: {exc}")
        return

    findings: list[str] = []
    for row in rows:
        status = row["item_status"]
        mode = row["session_mode"]
        age = _heartbeat_age_minutes(row["session_last_heartbeat"], now)
        fresh = row["session_ended_at"] is None and age is not None
        fresh = fresh and age <= ttl_minutes

        if status == "release" and (fresh and mode == "usher"):
            continue
        if status == "idea" and fresh and mode in _IDEA_DRAFT_MODES:
            continue

        age_text = f"{age:.1f}m" if age is not None else "unknown"
        ended_clause = " ended" if row["session_ended_at"] else ""
        recovery = (
            f"/yoke usher YOK-{int(row['item_id'])}"
            if status == "release"
            else "inspect/release the stale draft claim"
        )
        findings.append(
            f"  - YOK-{int(row['item_id'])} status={status} "
            f"holder={row['session_id']} mode={mode or '<none>'}{ended_clause} "
            f"heartbeat_age={age_text} claim_id={int(row['claim_id'])} "
            f"recovery: {recovery}"
        )

    if not findings:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    summary = (
        f"- {len(findings)} active item work-claim(s) held on a status whose "
        f"canonical role does not match the holder session. Release with the "
        f"halt-class reason (`usher-halt-*` for release items) or operator "
        f"release for stale idea drafts: "
        f"`python3 -m yoke_core.api.service_client release-work-claim "
        f"--item YOK-N --reason <terminal-intent>`."
    )
    issues = [summary] + findings[:_LIST_PREVIEW]
    if len(findings) > _LIST_PREVIEW:
        issues.append(f"  ... and {len(findings) - _LIST_PREVIEW} more")
    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = ["hc_work_claim_status_mismatch"]
