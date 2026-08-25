"""Contended session anchors must describe live contention, not a latch.

A contention marker in the machine-local session-anchor registry is the
fail-closed answer for a pid genuinely hosting two live sessions. The marker
heals on the next anchor write once at most one contender is still live — so
a marker whose recorded contenders are not two-or-more live sessions is a
stall: either the healing write has not happened (idle conversation) or the
marker predates contender recording and cannot heal on its own.

Machine-local by nature: the registry lives under the runner's machine home,
so this check says nothing about any other machine's anchors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from yoke_core.domain import db_backend

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_tree_scan import list_directory

HC_SLUG = "session-anchor-contention"
HC_LABEL = "Contended session anchors heal once contention ends"


def _contended_records() -> List[dict]:
    from yoke_core.domain.session_process_anchors import anchors_dir

    records: List[dict] = []
    directory = Path(anchors_dir())
    if not directory.is_dir():
        return records
    for path in list_directory(directory):
        if path.suffix != ".json":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get(
            "shared_by_multiple_sessions"
        ):
            record["_path"] = str(path)
            records.append(record)
    return records


def _anchor_process_live(record: dict) -> bool:
    from yoke_contracts.process_ancestry import process_start_time

    try:
        pid = int(record.get("anchor_pid"))
    except (TypeError, ValueError):
        return False
    recorded = record.get("anchor_start_time")
    return bool(recorded) and process_start_time(pid) == recorded


def _live_contenders(conn: Any, contenders: List[str]) -> List[str]:
    live: List[str] = []
    for session_id in contenders:
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        # Mirrors the healer's probe: an ended row or no row at all is
        # positively not a live session (rows are never deleted), so only
        # a live registration keeps a contender.
        if row is not None and row["ended_at"] is None:
            live.append(session_id)
    return live


def hc_session_anchor_contention(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _base._table_exists(conn, "harness_sessions"):
        rec.record(
            HC_SLUG, HC_LABEL, "SKIP",
            "harness_sessions table not present on this DB",
        )
        return
    try:
        contended = [
            record for record in _contended_records()
            if _anchor_process_live(record)
        ]
    except Exception as exc:  # noqa: BLE001 — an unreadable registry is a SKIP
        rec.record(HC_SLUG, HC_LABEL, "SKIP", f"anchor scan failed: {exc}")
        return
    if not contended:
        rec.record(
            HC_SLUG, HC_LABEL, "PASS",
            "no live contention markers in the session-anchor registry",
        )
        return

    stalled: List[str] = []
    genuine = 0
    for record in contended:
        contenders = [
            str(value)
            for value in record.get("contending_session_ids") or []
            if isinstance(value, str) and value
        ]
        try:
            live = _live_contenders(conn, contenders)
        except db_backend.database_error_types(conn) as exc:
            rec.record(
                HC_SLUG, HC_LABEL, "SKIP", f"liveness read failed: {exc}",
            )
            return
        if len(live) >= 2:
            genuine += 1
            continue
        stalled.append(
            f"- {record['_path']}: contenders={contenders or 'unrecorded'} "
            f"live={live} writer={record.get('last_writer_argv', '')!r}"
        )
    if not stalled:
        rec.record(
            HC_SLUG, HC_LABEL, "PASS",
            f"{genuine} contention marker(s) all describe >=2 live sessions",
        )
        return
    rec.record(
        HC_SLUG, HC_LABEL, "WARN",
        f"{len(stalled)} contention marker(s) no longer describe live "
        "contention:\n" + "\n".join(stalled) + "\n\n"
        "Each heals on the tenant session's next hook event; if the "
        "conversation is gone, delete the listed file(s).",
    )


__all__ = ["HC_LABEL", "HC_SLUG", "hc_session_anchor_contention"]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_LABEL, hc_session_anchor_contention),
)
