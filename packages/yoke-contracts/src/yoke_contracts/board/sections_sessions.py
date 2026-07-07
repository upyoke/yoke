"""Sessions and claims rendering for the board.

Owns the active-session and recently-closed-session tables, the keycap
numbering for grouped claims, executor / mode / lane emoji mappings,
and the aligned-table helpers the sessions section depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import item_ref
from yoke_contracts.board.sections_sessions_cells import session_common_cells
from yoke_contracts.board.sections_sessions_extra_claims import build_session_keycaps
from yoke_contracts.board.sections_sessions_layout import (
    _chunk_claims,
    _dedup_work_targets,
)
from yoke_contracts.board.sections_sessions_scope import session_rows
from yoke_contracts.board.utils import display_width


def _format_session_age(iso_ts: str) -> str:
    """Format an ISO timestamp as a human-readable relative age."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - ts
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except (ValueError, TypeError):
        return iso_ts[:16] if iso_ts else "?"


def _claims_for_session(db: BoardDBLike, session_id: str, active_only: bool) -> List[Tuple]:
    """Fetch claims for a session.

    Returns list of (item_id, epic_id, task_num, claim_type, claimed_at,
    released_at, release_reason, target_kind, process_key).
    """
    released_filter = "AND wc.released_at IS NULL" if active_only else ""
    return db.query_quiet(
        f"""
        SELECT wc.item_id, wc.epic_id, wc.task_num, wc.claim_type,
               wc.claimed_at, wc.released_at, wc.release_reason,
               wc.target_kind, wc.process_key
        FROM work_claims wc
        WHERE wc.session_id = %s
        {released_filter}
        ORDER BY wc.claimed_at DESC
        """,
        (session_id,),
    )


_MODE_EMOJI: Dict[str, str] = {
    "hook": "\U0001fa9d",          # hook
    "refine": "📝",      # 📝 pencil (matches refining-idea/-plan)
    "polish": "✨",            # sparkles (matches polishing-implementation)
    "charge": "⚡",            # high voltage
    "strategize": "\U0001f9e0",    # brain
    "escalate": "\U0001f6a8",      # rotating light
    "manual": "\U0001f527",  # 🔧 wrench
    "resume": "🔄",      # play/pause (resume)
    "advance": "⏩",           # fast-forward (ff)
    "wait": "⏳",              # hourglass flowing
    "conduct": "\U0001f3bc",       # musical score
    "shepherd": "\U0001f9d1‍\U0001f33e",  # farmer
    "usher": "\U0001f3ac",         # clapper board (directing the release)
    "curate": "\U0001f9f9",        # broom
    "doctor": "\U0001fa7a",        # stethoscope
    "simulate": "\U0001f52e",      # crystal ball
    "idea": "\U0001f4a1",          # light bulb
    "wrapup": "\U0001f9fe",        # receipt
    "do": "🎮",          # joystick
    "feed": "🍴",          # fork & knife (feed)
    "plan": "\U0001f4cc",    # 📌 pushpin
}

_LANE_EMOJI: Dict[str, str] = {
    "DARIUS": "\U0001f40e",        # horse
    "ALTMAN": "\U0001f453",        # glasses
}


def _render_lane(lane: Optional[str]) -> str:
    lane_emoji = _LANE_EMOJI.get(lane or "", "")
    return f"{lane_emoji} {lane}" if lane_emoji else (lane or "primary")


def _pad_cell(s: str, target_width: int) -> str:
    """Pad string to target display width with spaces."""
    pad = target_width - display_width(s)
    return s + " " * max(pad, 0)


def _aligned_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Build a markdown table with columns padded to uniform display width."""
    ncols = len(headers)
    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row[:ncols]):
            widths[i] = max(widths[i], display_width(cell))
    sep = ["-" * w for w in widths]
    def _fmt(cells: list[str]) -> str:
        padded = [_pad_cell(cells[i], widths[i]) for i in range(ncols)]
        return "| " + " | ".join(padded) + " |"
    out = [_fmt(headers), "| " + " | ".join(sep) + " |"]
    for row in rows:
        out.append(_fmt(row))
    return out


def _render_claim_target(
    item_id,
    epic_id: Optional[int],
    task_num: Optional[int],
    process_key: Optional[str] = None,
    *,
    db: Optional[BoardDBLike] = None,
) -> str:
    """Format a claim target as a readable string.

    ``work_claims.item_id`` is numeric, so DB rows hand us an int here even
    though the YOK-N display form is a string. Coerce before checking the
    prefix.
    """
    if process_key:
        return f"🔩 {process_key}"
    if item_id is not None:
        if db is not None:
            try:
                return item_ref(db, int(item_id))
            except Exception:
                pass
        item_str = str(item_id)
        return item_str if item_str.startswith("YOK-") else f"YOK-{item_str}"
    if epic_id is not None and task_num is not None:
        if db is not None:
            try:
                return f"{item_ref(db, int(epic_id))} T{task_num:03d}"
            except Exception:
                pass
        return f"YOK-{epic_id} T{task_num:03d}"
    return "?"


def render_sessions_section(
    db: BoardDBLike, *, show_recent: bool = True, scope: str = "all"
) -> str:
    """Render active sessions + 3 most recently closed sessions with their claims.

    Args:
        db: Open database handle.
        show_recent: When False, suppress the "Recent Harness Sessions" table.

    Returns complete markdown section string, or empty string if no sessions exist.
    """
    harness_sessions = session_rows(db, scope=scope, active_only=True)
    closed_sessions = session_rows(db, scope=scope, active_only=False)
    if not harness_sessions and not closed_sessions:
        return ""

    lines: List[str] = []

    # --- Active Harness Sessions ---
    if harness_sessions:
        lines.append(f"### \U0001f7e2 Active Harness Sessions ({len(harness_sessions)})")
        lines.append("")

        table_rows: list[list[str]] = []
        for row in harness_sessions:
            (
                sid, executor, executor_display_name, model, mode, lane,
                offered_at, last_hb, workspace, project_id,
            ) = row
            age = _format_session_age(offered_at or "")

            # Get active claims for this session (work_claims + path_claims + leases)
            claims = _claims_for_session(db, sid, active_only=True)
            work_targets = _dedup_work_targets([
                (
                    _render_claim_target(c[0], c[1], c[2], c[8], db=db),
                    c[0],
                    None,
                )
                for c in claims
            ])
            keycaps = build_session_keycaps(
                db, sid, work_targets, active_only=True,
            )
            claim_rows = _chunk_claims(keycaps) if keycaps else ["—"]

            mode_emoji = _MODE_EMOJI.get(mode or "", "")
            mode_str = f"{mode_emoji} {mode}" if mode_emoji else (mode or "wait")
            lane_str = _render_lane(lane)
            common_cells = session_common_cells(
                db, sid, executor, executor_display_name, model, project_id,
            )

            for idx, claims_str in enumerate(claim_rows):
                if idx == 0:
                    table_rows.append([
                        *common_cells, lane_str, mode_str, age, claims_str,
                    ])
                else:
                    table_rows.append(["", "", "", "", "", "", "", claims_str])

        lines.extend(_aligned_table(
            [
                "Session", "Project", "Executor", "Model",
                "Lane", "Mode", "Age", "Claims",
            ],
            table_rows,
        ))
        lines.append("")

    # --- Recently Closed Sessions ---
    if closed_sessions and show_recent:
        lines.append(f"### 🔴 Recent Harness Sessions ({len(closed_sessions)})")
        lines.append("")

        table_rows_closed: list[list[str]] = []
        for row in closed_sessions:
            (
                sid, executor, executor_display_name, model, mode, lane,
                offered_at, last_hb, workspace, project_id, ended_at,
            ) = row
            ended_age = _format_session_age(ended_at or "")

            # Compute duration
            duration = "—"
            try:
                start = datetime.fromisoformat((offered_at or "").replace("Z", "+00:00"))
                end = datetime.fromisoformat((ended_at or "").replace("Z", "+00:00"))
                dur_secs = int((end - start).total_seconds())
                if dur_secs < 60:
                    duration = f"{dur_secs}s"
                elif dur_secs < 3600:
                    duration = f"{dur_secs // 60}m"
                else:
                    duration = f"{dur_secs // 3600}h{(dur_secs % 3600) // 60}m"
            except (ValueError, TypeError):
                pass

            # Get ALL claims for closed session (work_claims + path_claims + leases)
            claims = _claims_for_session(db, sid, active_only=False)
            work_targets = _dedup_work_targets([
                (
                    _render_claim_target(c[0], c[1], c[2], c[8], db=db),
                    c[0],
                    c[6],
                )
                for c in claims
            ])
            keycaps = build_session_keycaps(
                db, sid, work_targets, active_only=False,
            )
            claim_rows = _chunk_claims(keycaps) if keycaps else ["—"]

            common_cells = session_common_cells(
                db, sid, executor, executor_display_name, model, project_id,
            )
            lane_str = _render_lane(lane)

            for idx, claims_str in enumerate(claim_rows):
                if idx == 0:
                    table_rows_closed.append([
                        *common_cells, lane_str, f"{ended_age} ago", duration,
                        claims_str,
                    ])
                else:
                    table_rows_closed.append(["", "", "", "", "", "", "", claims_str])

        lines.extend(_aligned_table(
            [
                "Session", "Project", "Executor", "Model",
                "Lane", "Ended", "Duration", "Claims",
            ],
            table_rows_closed,
        ))
        lines.append("")

    # Strip trailing blank line — caller controls spacing
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
