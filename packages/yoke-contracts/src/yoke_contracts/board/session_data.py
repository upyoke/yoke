"""Connection-free layout of named board session facts."""

from typing import Any, Mapping, Sequence

from yoke_contracts.board.sections_sessions_layout import _chunk_claims
from yoke_contracts.board.sections_sessions_rendering import (
    _aligned_table,
    _format_session_age,
)
from yoke_contracts.timestamps import parse_instant


def _parked_cell(mode: str | None) -> str:
    """Show the explicit parked posture without decorating command names."""
    return "parked" if str(mode or "").lower() == "parked" else ""


def _duration(start, end) -> str:
    if start is None or end is None:
        return "—"
    seconds = max(0, int((parse_instant(end) - parse_instant(start)).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60}m"


def _session_table(sessions: Sequence[Mapping[str, Any]], *, ended: bool) -> list[str]:
    rows = []
    for session in sessions:
        common = [
            str(session[key])
            for key in (
                "session",
                "project",
                "executor",
                "model",
                "usage",
                "level",
            )
        ]
        if ended:
            timing = [
                f"{_format_session_age(session['ended_at'])} ago",
                _duration(session["offered_at"], session["ended_at"]),
            ]
        else:
            timing = [
                _parked_cell(session["mode"]),
                _format_session_age(session["offered_at"]),
            ]
        holdings = _chunk_claims(session["holdings"]) or ["—"]
        rows.append([*common, *timing, holdings[0]])
        rows.extend(
            ["", "", "", "", "", "", "", "", holding] for holding in holdings[1:]
        )
    headers = ["Session", "Project", "Executor", "Model", "Usage", "Level"]
    headers.extend(["Ended", "Duration"] if ended else ["Parked", "Age"])
    return _aligned_table([*headers, "Claims"], rows)


def render_session_rows(
    active: Sequence[Mapping[str, Any]],
    recent: Sequence[Mapping[str, Any]],
    *,
    show_recent: bool = True,
) -> str:
    """Render session facts without database access or SQL replay."""
    lines = []
    for sessions, ended, heading in (
        (active, False, "🟢 Active Harness Sessions"),
        (recent if show_recent else [], True, "🔴 Recent Harness Sessions"),
    ):
        if not sessions:
            continue
        if lines:
            lines.append("")
        lines.extend([f"### {heading} ({len(sessions)})", ""])
        lines.extend(_session_table(sessions, ended=ended))
    return "\n".join(lines)
