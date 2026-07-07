"""Zen widget — label and vision computation.

Stopword parsing, keyword-frequency labels for the past zone, and VISION.md
section extraction. Imports the canonical stopword set, vision-section map,
and repo-root locator from :mod:`zen_data`.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.zen_data import (
    _MAX_LABELS,
    _STOP_WORDS,
    _VISION_SECTIONS,
    _zen_project_id,
)
from yoke_contracts.time_sql import now_sql


def _parse_extra_stopwords(raw: str) -> frozenset:
    """Parse a comma-separated stopwords string into a lowercase set."""
    if not raw:
        return frozenset()
    parts = (p.strip().lower() for p in raw.split(","))
    return frozenset(p for p in parts if p)


def _labels_for_window(
    db: BoardDBLike,
    project: str,
    window_start: str,
    label_days: int,
    df_cap_pct: int,
    extra_stops: frozenset,
) -> List[str]:
    """Single-pass label computation for one specific window."""
    project_id = _zen_project_id(db, project)
    if label_days > 0:
        rows = db.query(
            "SELECT title FROM items "
            "WHERE project_id = %s AND status = 'done' "
            f"AND created_at >= {now_sql(offset_modifier='%s', localtime=True)} "
            "ORDER BY created_at",
            (project_id, f"-{label_days} days"),
        )
    else:
        rows = db.query(
            "SELECT title FROM items "
            "WHERE project_id = %s AND status = 'done' AND created_at >= %s "
            "ORDER BY created_at",
            (project_id, window_start),
        )

    stops = _STOP_WORDS | extra_stops

    keywords: List[str] = []
    for (title,) in rows:
        # Strip from the first non-alpha/space character.
        cleaned = re.sub(r"[^a-zA-Z ].*", "", title).lower()
        words = cleaned.split()
        for word in words:
            if len(word) >= 3 and word not in stops:
                keywords.append(word)
                break

    if not keywords:
        return []

    freq = {}
    for word in keywords:
        freq[word] = freq.get(word, 0) + 1

    # Doc-frequency cap: drop over-common words that carry no signal.
    if df_cap_pct > 0:
        total = len(keywords)
        threshold = total * df_cap_pct / 100.0
        freq = {w: c for w, c in freq.items() if c <= threshold}

    if not freq:
        return []

    ranked = sorted(freq.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return [word for word, _count in ranked[:_MAX_LABELS]]


def _zen_compute_labels(
    db: BoardDBLike,
    project: str,
    window_start: str,
    label_days: int = 0,
    df_cap_pct: int = 0,
    extra_stops: frozenset = frozenset(),
    min_labels: int = 0,
) -> List[str]:
    """Feature labels from keyword frequency (max 10, max 12 chars each).

    When *label_days* > 0, the label window narrows to the last N days so
    the ranking reflects recent work rather than the all-time histogram —
    with 2000+ done items, the all-time top-10 is effectively frozen.

    When *df_cap_pct* > 0, any word whose document-frequency share exceeds
    ``df_cap_pct / 100`` is dropped. Catches words so common they carry no
    discriminating signal (e.g. a project where "browser" is the head
    keyword in 40% of titles).

    *extra_stops* augments the hardcoded :data:`_STOP_WORDS` set.

    When *min_labels* > 0, if the requested window yields fewer than N
    labels the window is progressively widened (3x, 10x, all-time) until
    the floor is met or we run out of history — keeps low-volume projects
    from collapsing to a handful of sparse labels.
    """
    labels = _labels_for_window(
        db, project, window_start, label_days, df_cap_pct, extra_stops
    )

    if min_labels > 0 and len(labels) < min_labels and label_days > 0:
        for attempt in (label_days * 3, label_days * 10, 0):
            widened = _labels_for_window(
                db, project, window_start, attempt, df_cap_pct, extra_stops
            )
            if len(widened) > len(labels):
                labels = widened
            if len(labels) >= min_labels or attempt == 0:
                break

    return labels


def _zen_extract_vision(repo_root: Optional[str]) -> List[Tuple[str, str]]:
    """Parse the rendered VISION strategy doc for timeline zone labels.

    Returns ``(key, label)`` tuples, e.g. ``("1mo", "autonomous")``.
    """
    if not repo_root:
        return []
    from yoke_contracts.project_contract.strategy_docs_paths import strategy_view_path

    vision_path = str(strategy_view_path(repo_root, "VISION"))
    if not os.path.isfile(vision_path):
        return []

    try:
        with open(vision_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return []

    results: List[Tuple[str, str]] = []
    for section_name, key in _VISION_SECTIONS:
        pattern = re.compile(
            r"^### " + re.escape(section_name) + r"\s*\n(.*?)(?=^### |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        m = pattern.search(content)
        if not m:
            continue
        block = m.group(1)
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- "):
                text = line[2:].strip()
                words = text.split()[:2]
                label = " ".join(words).lower()[:12]
                if label:
                    results.append((key, label))
                break

    return results


__all__ = [
    "_parse_extra_stopwords",
    "_labels_for_window",
    "_zen_compute_labels",
    "_zen_extract_vision",
]
