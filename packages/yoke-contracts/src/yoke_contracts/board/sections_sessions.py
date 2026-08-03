"""Sessions and claims rendering for the board.

Owns the active-session and recently-closed-session tables, the keycap
numbering for grouped claims, executor / mode / lane emoji mappings,
and the aligned-table helpers the sessions section depends on.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_sessions_cells import session_common_cells
from yoke_contracts.board.sections_sessions_extra_claims import build_session_keycaps
from yoke_contracts.board.sections_sessions_layout import (
    _chunk_claims,
    _dedup_work_targets,
)
from yoke_contracts.board.sections_sessions_scope import session_rows
from yoke_contracts.board.sections_sessions_scope import session_lane_presentation
from yoke_contracts.board.sections_sessions_rendering import (
    _MODE_EMOJI,
    _aligned_table,
    _claims_for_session,
    _format_session_age,
    _render_claim_target,
    _render_lane,
)


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
        lines.append(
            f"### \U0001f7e2 Active Harness Sessions ({len(harness_sessions)})"
        )
        lines.append("")

        table_rows: list[list[str]] = []
        for row in harness_sessions:
            (
                sid,
                executor,
                executor_display_name,
                model,
                mode,
                lane,
                offered_at,
                last_hb,
                workspace,
                project_id,
            ) = row
            age = _format_session_age(offered_at or "")

            # Get active claims for this session (work_claims + path_claims + leases)
            claims = _claims_for_session(db, sid, active_only=True)
            work_targets = _dedup_work_targets(
                [
                    (
                        _render_claim_target(c[0], c[1], c[2], c[8], db=db),
                        c[0],
                        None,
                    )
                    for c in claims
                ]
            )
            keycaps = build_session_keycaps(
                db,
                sid,
                work_targets,
                active_only=True,
            )
            claim_rows = _chunk_claims(keycaps) if keycaps else ["—"]

            mode_emoji = _MODE_EMOJI.get(mode or "", "")
            mode_str = f"{mode_emoji} {mode}" if mode_emoji else (mode or "wait")
            lane_str = _render_lane(
                lane,
                session_lane_presentation(db, project_id, lane),
            )
            common_cells = session_common_cells(
                db,
                sid,
                executor,
                executor_display_name,
                model,
                project_id,
            )

            for idx, claims_str in enumerate(claim_rows):
                if idx == 0:
                    table_rows.append(
                        [
                            *common_cells,
                            lane_str,
                            mode_str,
                            age,
                            claims_str,
                        ]
                    )
                else:
                    table_rows.append(["", "", "", "", "", "", "", claims_str])

        lines.extend(
            _aligned_table(
                [
                    "Session",
                    "Project",
                    "Executor",
                    "Model",
                    "Lane",
                    "Mode",
                    "Age",
                    "Claims",
                ],
                table_rows,
            )
        )
        lines.append("")

    # --- Recently Closed Sessions ---
    if closed_sessions and show_recent:
        lines.append(f"### 🔴 Recent Harness Sessions ({len(closed_sessions)})")
        lines.append("")

        table_rows_closed: list[list[str]] = []
        for row in closed_sessions:
            (
                sid,
                executor,
                executor_display_name,
                model,
                mode,
                lane,
                offered_at,
                last_hb,
                workspace,
                project_id,
                ended_at,
            ) = row
            ended_age = _format_session_age(ended_at or "")

            # Compute duration
            duration = "—"
            try:
                start = datetime.fromisoformat(
                    (offered_at or "").replace("Z", "+00:00")
                )
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
            work_targets = _dedup_work_targets(
                [
                    (
                        _render_claim_target(c[0], c[1], c[2], c[8], db=db),
                        c[0],
                        c[6],
                    )
                    for c in claims
                ]
            )
            keycaps = build_session_keycaps(
                db,
                sid,
                work_targets,
                active_only=False,
            )
            claim_rows = _chunk_claims(keycaps) if keycaps else ["—"]

            common_cells = session_common_cells(
                db,
                sid,
                executor,
                executor_display_name,
                model,
                project_id,
            )
            lane_str = _render_lane(
                lane,
                session_lane_presentation(db, project_id, lane),
            )

            for idx, claims_str in enumerate(claim_rows):
                if idx == 0:
                    table_rows_closed.append(
                        [
                            *common_cells,
                            lane_str,
                            f"{ended_age} ago",
                            duration,
                            claims_str,
                        ]
                    )
                else:
                    table_rows_closed.append(["", "", "", "", "", "", "", claims_str])

        lines.extend(
            _aligned_table(
                [
                    "Session",
                    "Project",
                    "Executor",
                    "Model",
                    "Lane",
                    "Ended",
                    "Duration",
                    "Claims",
                ],
                table_rows_closed,
            )
        )
        lines.append("")

    # Strip trailing blank line — caller controls spacing
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
