"""Latest attempt plus how often delivery already failed for one receipt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.session_control.wake_delivery import delivery_attempt_failed
from yoke_core.domain import json_helper
from yoke_core.domain.steering_fleet_report_delivery_states import (
    deliverable_receipt,
)


@dataclass(frozen=True)
class AttemptView:
    """One receipt's newest attempt, with the failures that preceded it."""

    result_code: str
    evidence: Mapping[str, Any]
    failed_count: int
    last_failed_code: str
    last_failed_evidence: Mapping[str, Any]


def _evidence(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json_helper.loads_text(raw)
        except (TypeError, ValueError):
            return {}
    return raw if isinstance(raw, Mapping) else {}


def last_attempts(
    conn: Any, *, project_id: int, marker: str, now: str
) -> dict[tuple[str, str], AttemptView]:
    """Return each undelivered receipt's attempt history, keyed by receipt."""
    rows = conn.execute(
        f"""SELECT a.message_id AS message_id,
                   a.target_session_id AS target_session_id,
                   a.result_code AS result_code,
                   a.evidence AS evidence
              FROM session_message_attempts a
              JOIN session_message_recipients r
                ON r.message_id = a.message_id
               AND r.session_id = a.target_session_id
              JOIN session_messages m ON m.message_id = r.message_id
             WHERE {deliverable_receipt(marker)}
             ORDER BY a.started_at, a.attempt_id""",
        (int(project_id), now),
    ).fetchall()
    latest: dict[tuple[str, str], AttemptView] = {}
    for raw in rows:
        row = dict(raw)
        key = (str(row["message_id"]), str(row["target_session_id"]))
        code = str(row.get("result_code") or "")
        evidence = _evidence(row.get("evidence"))
        prior = latest.get(key)
        failed_count = prior.failed_count if prior else 0
        last_failed_code = prior.last_failed_code if prior else ""
        last_failed_evidence = prior.last_failed_evidence if prior else {}
        if delivery_attempt_failed(code):
            failed_count += 1
            last_failed_code = code
            last_failed_evidence = evidence
        latest[key] = AttemptView(
            result_code=code,
            evidence=evidence,
            failed_count=failed_count,
            last_failed_code=last_failed_code,
            last_failed_evidence=last_failed_evidence,
        )
    return latest


__all__ = ["AttemptView", "last_attempts"]
