"""Verdict, shepherd-log, and caveat disposition commands."""
from __future__ import annotations

import json
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.shepherd_records import format_row, now_iso

VALID_DISPOSITIONS = frozenset({"RESOLVED", "DEFERRED", "ANALYZED"})


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _emit_event(item: str, event_name: str, context: str) -> None:
    try:
        from yoke_core.domain.events import emit_event as native_emit

        try:
            context_obj = json.loads(context) if context else None
        except (TypeError, ValueError):
            context_obj = {"raw": context}
        native_emit(
            event_name,
            event_kind="workflow",
            event_type="verdict_rendered",
            source_type="skill",
            severity="STATUS",
            outcome="completed",
            item_id=item,
            context=context_obj,
        )
    except Exception:
        pass


def cmd_verdict(
    conn,
    item: str,
    transition: str,
    worker: str,
    verdict: str,
    caveats: Optional[str] = None,
) -> str:
    ts = now_iso()
    p = _placeholder(conn)
    prev = query_scalar(
        conn,
        "SELECT COALESCE(MAX(attempt), 0) FROM shepherd_verdicts "
        f"WHERE item={p} AND transition={p} AND worker={p}",
        (item, transition, worker),
    )
    attempt = (prev or 0) + 1
    cursor = conn.execute(
        "INSERT INTO shepherd_verdicts "
        "(item, transition, worker, verdict, caveats, attempt, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (item, transition, worker, verdict, caveats, attempt, ts),
    )
    verdict_id = int(cursor.fetchone()[0])
    conn.commit()

    context = {"transition": transition, "worker": worker, "verdict": verdict}
    if caveats:
        context["caveats"] = caveats
    _emit_event(item, "VerdictRendered", json.dumps(context))
    return str(verdict_id)


def cmd_shepherd_log(conn, item: str) -> str:
    p = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT transition, worker, verdict, "
        "COALESCE(caveats, ''), "
        "attempt, created_at "
        f"FROM shepherd_verdicts WHERE item={p} ORDER BY id",
        (item,),
    )
    lines = ["## Shepherd Log"]
    if not rows:
        lines.append("")
        lines.append("<!-- No verdicts recorded -->")
        return "\n".join(lines)

    dispositions = query_rows(
        conn,
        "SELECT transition, attempt, caveat_num, disposition, "
        "COALESCE(resolution_details, '') "
        f"FROM caveat_dispositions WHERE item={p} "
        "ORDER BY transition, attempt, caveat_num",
        (item,),
    )
    disp_map = {(row[0], row[1], row[2]): (row[3], row[4]) for row in dispositions}

    for row in rows:
        transition, worker, verdict, caveats_raw, attempt, created_at = tuple(row)
        date = created_at.split("T")[0] if "T" in str(created_at) else str(created_at)
        lines.append("")
        lines.append(f"### {transition} -- {date}")
        lines.append(f"- **Worker:** {worker} (attempt {attempt})")
        lines.append(f"- **Boss verdict:** {verdict}")
        if verdict == "CAVEATS" and caveats_raw:
            _append_caveat_lines(lines, disp_map, transition, attempt, caveats_raw)
    return "\n".join(lines)


def _append_caveat_lines(
    lines: list[str],
    disp_map: dict,
    transition: str,
    attempt: int,
    caveats_raw: str,
) -> None:
    lines.append("- **Caveats:**")
    caveat_num = 0
    for caveat_line in caveats_raw.split("\n"):
        if not caveat_line.strip():
            continue
        caveat_num += 1
        disposition = disp_map.get((transition, attempt, caveat_num))
        if not disposition:
            lines.append(f"  {caveat_num}. {caveat_line}")
            continue
        disposition_type, details = disposition
        details = details.split("\n")[0] if details else ""
        if details:
            lines.append(
                f"  {caveat_num}. {caveat_line} -> **{disposition_type}:** {details}"
            )
        else:
            lines.append(f"  {caveat_num}. {caveat_line} -> **{disposition_type}**")


def cmd_caveat_disposition(
    conn,
    item: str,
    transition: str,
    attempt: int,
    caveat_num: int,
    caveat_text: str,
    disposition: str,
    resolution_details: Optional[str] = None,
    verdict_id: Optional[int] = None,
) -> str:
    if disposition not in VALID_DISPOSITIONS:
        raise ValueError(
            f"disposition must be {', '.join(sorted(VALID_DISPOSITIONS))} "
            f"(got '{disposition}')"
        )
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO caveat_dispositions "
        "(item, transition, attempt, caveat_num, caveat_text, disposition, "
        "resolution_details, verdict_id, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(item, transition, attempt, caveat_num) DO UPDATE SET "
        "caveat_text=EXCLUDED.caveat_text, disposition=EXCLUDED.disposition, "
        "resolution_details=EXCLUDED.resolution_details, "
        "verdict_id=EXCLUDED.verdict_id, created_at=EXCLUDED.created_at",
        (
            item,
            transition,
            attempt,
            caveat_num,
            caveat_text,
            disposition,
            resolution_details,
            verdict_id,
            now_iso(),
        ),
    )
    conn.commit()
    return "OK"


def cmd_caveat_dispositions(conn, item: str) -> str:
    p = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT item, transition, attempt, caveat_num, caveat_text, disposition, "
        "COALESCE(resolution_details, ''), COALESCE(CAST(verdict_id AS TEXT), ''), created_at "
        f"FROM caveat_dispositions WHERE item={p} "
        "ORDER BY transition, attempt, caveat_num",
        (item,),
    )
    return "\n".join(format_row(row) for row in rows)
