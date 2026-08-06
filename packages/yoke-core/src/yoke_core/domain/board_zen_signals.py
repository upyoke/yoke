"""Shared board/Overview zen timeline payload.

One zone/label/position algorithm (board ``zen_data`` / ``zen_labels``) so
Overview HTML and the terminal zen widget cannot diverge on the same scope.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.zen_data import (
    _WIDTH,
    _zen_compute_window,
    _zen_compute_zones,
    _zen_item_positions,
    _zen_query_items,
    _zen_queued_count,
)
from yoke_contracts.board.zen_labels import (
    _parse_extra_stopwords,
    _zen_compute_labels,
    vision_from_content,
)


class ConnBoardDB:
    """Adapt a dict-row psycopg connection to :class:`BoardDBLike` tuples."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def query(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]:
        cur = self._conn.execute(sql, tuple(params) if params else ())
        return [tuple(row) for row in cur.fetchall()]

    def query_quiet(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]:
        try:
            return self.query(sql, params)
        except Exception:
            return []

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        rows = self.query(sql, params)
        return rows[0][0] if rows else None


def _vision_for_project(conn: Any, project_id: int, slug: str) -> List[Tuple[str, str]]:
    """VISION horizons for zen — board applies VISION only to ``yoke``."""

    if slug != "yoke":
        return []
    row = conn.execute(
        "SELECT content FROM strategy_docs "
        "WHERE project_id = %s AND slug = 'VISION' "
        "AND archived_at IS NULL",
        (project_id,),
    ).fetchone()
    if not row:
        return []
    content = row["content"] if hasattr(row, "keys") else row[0]
    return vision_from_content(str(content or ""))


def _label_positions(labels: List[str], past_width: int) -> List[Dict[str, Any]]:
    """Evenly space frequency labels across the past zone (board layout)."""

    if not labels or past_width <= 0:
        return []
    count = len(labels)
    per = max(3, past_width // count)
    out: List[Dict[str, Any]] = []
    for idx, lab in enumerate(labels):
        center = (idx * per) + (per / 2.0)
        pct = round(min(100.0, max(0.0, center / past_width * 100.0)), 1)
        out.append({"position": pct, "label": lab[:12]})
    return out


def _project_zen(
    db: ConnBoardDB,
    *,
    project_id: int,
    slug: str,
    emoji: str,
    vision_entries: List[Tuple[str, str]],
    label_days: int,
    df_cap_pct: int,
    extra_stops: frozenset,
    min_labels: int,
) -> Optional[Dict[str, Any]]:
    window = _zen_compute_window(db, slug)
    if not window:
        return None
    items = _zen_query_items(db, slug, window)
    if not items:
        return None

    queued = _zen_queued_count(db, slug)
    has_queued = queued > 0
    vision_count = len(vision_entries)
    zones = _zen_compute_zones(_WIDTH, True, has_queued, vision_count)
    past_width = 80
    zone_payload: List[Dict[str, Any]] = []
    for zname, zwidth, _zcol in zones:
        if zname == "past":
            past_width = zwidth
        entry: Dict[str, Any] = {"key": zname, "width": int(zwidth)}
        if zname == "near":
            entry["label"] = f"{queued} queued"
        zone_payload.append(entry)

    # Attach VISION labels onto vision-named zones in order.
    vision_iter = iter(vision_entries)
    for entry in zone_payload:
        if entry["key"] in ("past", "present", "near"):
            continue
        try:
            key, label = next(vision_iter)
        except StopIteration:
            break
        entry["key"] = key
        entry["label"] = label

    labels = _zen_compute_labels(
        db, slug, window, label_days, df_cap_pct, extra_stops, min_labels,
    )
    positions = _zen_item_positions(db, slug, window, past_width)
    denom = max(past_width - 1, 1)
    done_pct = [
        round(min(100.0, max(0.0, pos / denom * 100.0)), 1)
        for pos in positions
    ]
    return {
        "project_id": project_id,
        "project": slug,
        "emoji": emoji,
        "zones": zone_payload,
        "done_positions": done_pct,
        "labels": _label_positions(labels, past_width),
        "queued_count": queued,
        "vision_zones": [
            {"key": key, "label": label} for key, label in vision_entries
        ],
    }


def build_zen_payloads(
    conn: Any,
    project_ids: list[int],
    *,
    config: Optional[BoardConfig] = None,
) -> list[dict[str, Any]]:
    """Build one board-shaped zen payload per project that has done work."""

    if not project_ids:
        return []
    if config is None:
        from yoke_core.domain.board_policy_read import resolve_board_config

        config = resolve_board_config(conn, project_ids[0])

    label_days = max(0, int(config.timeline_label_days or 0))
    df_cap_pct = max(0, int(config.timeline_label_df_cap_pct or 0))
    extra_stops = _parse_extra_stopwords(config.timeline_extra_stopwords)
    min_labels = max(0, int(config.timeline_label_min or 0))

    markers = ", ".join("%s" for _ in project_ids)
    projects = conn.execute(
        "SELECT id, slug, COALESCE(emoji, '') AS emoji "
        f"FROM projects WHERE id IN ({markers}) ORDER BY id",
        tuple(project_ids),
    ).fetchall()

    db = ConnBoardDB(conn)
    payloads: list[dict[str, Any]] = []
    for project in projects:
        project_id = int(project["id"])
        slug = str(project["slug"])
        emoji = str(project["emoji"] or "")
        vision = _vision_for_project(conn, project_id, slug)
        built = _project_zen(
            db,
            project_id=project_id,
            slug=slug,
            emoji=emoji,
            vision_entries=vision,
            label_days=label_days,
            df_cap_pct=df_cap_pct,
            extra_stops=extra_stops,
            min_labels=min_labels,
        )
        if built is not None:
            payloads.append(built)
    return payloads


__all__ = [
    "ConnBoardDB",
    "build_zen_payloads",
]
