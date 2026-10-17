"""Row readers the QA gate summary shares with the done gate."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_contracts.timestamps import format_instant, parse_instant


def post_deploy_answered(conn: Any, row: Any) -> bool:
    """An item post_deploy row is answered by delivery, as the done gate reads it."""
    if (
        str(row["qa_phase"] or "") != "post_deploy"
        or row["deployment_run_id"]
        or row["item_id"] is None
    ):
        return False
    from yoke_core.domain.deployment_qa_source_obligation import (
        source_obligation_consumed,
    )

    return source_obligation_consumed(
        conn, item_id=int(row["item_id"]), source_requirement_id=int(row["id"])
    )


def format_run(row: Optional[Any]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    verdict = row["verdict"] if "verdict" in row.keys() else None
    return {
        "id": int(row["id"]),
        "verdict": str(verdict) if verdict else None,
        "verdict_reason": row["verdict_reason"],
        "performed_by": str(row["performed_by"]),
        "created_at": format_instant(parse_instant(row["created_at"]))
        if row["created_at"] is not None
        else None,
    }


def unsettled_record_rows(conn: Any, item_id: int) -> List[Dict[str, str]]:
    """The done gate's own terminal-settlement records for this item.

    The summary reads :func:`find_unsettled_records`, the check the status
    write refuses on, so "satisfied" here cannot disagree with that refusal.
    """
    from yoke_core.domain.qa_terminal_settlement import find_unsettled_records

    return [
        {"kind": record.kind, "record_id": record.record_id, "detail": record.detail}
        for record in find_unsettled_records(conn, item_id=int(item_id))
    ]
