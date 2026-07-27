"""Strategy-timeline shaping for the universe Overview."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional

_QUEUED_STATUSES = ("idea", "planned", "refined-idea", "refining-idea")
_TIMELINE_LABEL_LIMIT = 6


def _timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timeline_position(
    value: Any,
    *,
    window_start: datetime,
    window_end: datetime,
) -> int:
    parsed = _timestamp(value) or window_start
    span = max(1.0, (window_end - window_start).total_seconds())
    elapsed = max(0.0, min(span, (parsed - window_start).total_seconds()))
    return round(elapsed / span * 100)


def _timeline_label(title: Any) -> str:
    from yoke_contracts.board.zen_data import _STOP_WORDS

    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", str(title or "").lower())
    meaningful = [word for word in words if word not in _STOP_WORDS]
    return " ".join((meaningful or words)[:2])[:18]


def _vision_zones(content: Any) -> list[dict[str, str]]:
    from yoke_contracts.board.zen_data import _VISION_SECTIONS

    text = str(content or "")
    zones: list[dict[str, str]] = []
    for section_name, key in _VISION_SECTIONS:
        match = re.search(
            r"^### " + re.escape(section_name) + r"\s*\n(.*?)(?=^### |\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not match:
            continue
        for line in match.group(1).splitlines():
            candidate = line.strip()
            if not candidate.startswith("- "):
                continue
            label = " ".join(candidate[2:].strip().split()[:2]).lower()[:18]
            if label:
                zones.append({"key": key, "label": label})
            break
    return zones


def strategy_timelines(
    conn: Any,
    project_ids: list[int],
    *,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Build one completion/queue/vision timeline per visible project."""
    if not project_ids:
        return []
    markers = ", ".join("%s" for _ in project_ids)
    projects = conn.execute(
        "SELECT id, slug, COALESCE(emoji, '') AS emoji "
        f"FROM projects WHERE id IN ({markers}) ORDER BY id",
        tuple(project_ids),
    ).fetchall()
    window_end = now or datetime.now(timezone.utc)
    timelines: list[dict[str, Any]] = []
    for project in projects:
        project_id = int(project["id"])
        done_rows = conn.execute(
            "SELECT id, title, created_at FROM items "
            "WHERE project_id = %s AND status = 'done' ORDER BY created_at",
            (project_id,),
        ).fetchall()
        parsed_dates = [
            parsed
            for row in done_rows
            if (parsed := _timestamp(row["created_at"])) is not None
        ]
        window_start = min(parsed_dates) if parsed_dates else window_end
        positions: list[int] = []
        labels: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        for row in done_rows:
            position = _timeline_position(
                row["created_at"],
                window_start=window_start,
                window_end=window_end,
            )
            if not positions or all(abs(position - other) >= 2 for other in positions):
                positions.append(position)
            label = _timeline_label(row["title"])
            if (
                label
                and label not in seen_labels
                and len(labels) < _TIMELINE_LABEL_LIMIT
            ):
                labels.append({"position": position, "label": label})
                seen_labels.add(label)
        queued_row = conn.execute(
            "SELECT COUNT(*) AS total FROM items "
            "WHERE project_id = %s "
            "AND (status IN (%s, %s, %s, %s) "
            "OR (COALESCE(frozen, 0) = 1 "
            "AND status NOT IN ('done', 'cancelled', 'stopped', 'failed')))",
            (project_id, *_QUEUED_STATUSES),
        ).fetchone()
        vision_row = conn.execute(
            "SELECT content FROM strategy_docs "
            "WHERE project_id = %s AND slug = 'VISION' "
            "AND archived_at IS NULL",
            (project_id,),
        ).fetchone()
        timelines.append(
            {
                "project_id": project_id,
                "project": str(project["slug"]),
                "emoji": str(project["emoji"] or ""),
                "done_positions": positions,
                "labels": labels,
                "queued_count": int(queued_row["total"]) if queued_row else 0,
                "vision_zones": _vision_zones(
                    vision_row["content"] if vision_row else "",
                ),
            }
        )
    return timelines


__all__ = ["strategy_timelines"]
