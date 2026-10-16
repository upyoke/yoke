"""Client-side timeline layout from named project facts and local VISION labels."""

from typing import List, Tuple

_DASH = "━"  # ━  BOX DRAWINGS HEAVY HORIZONTAL
_DOT = "●"  # ●  BLACK CIRCLE
_PRESENT = " \U0001f538 "  # 🔸  with surrounding spaces
_DASHED = "╌"  # ╌  BOX DRAWINGS LIGHT DOUBLE DASH HORIZONTAL
_DOTTED = "┄"  # ┄  BOX DRAWINGS LIGHT TRIPLE DASH HORIZONTAL
_MIDDLE_DOT = "·"  # ·
_TILDE = "~"


def _pad(n: int, char: str) -> str:
    """Return *n* copies of *char*."""
    return char * n


def _truncate(s: str, maxlen: int) -> str:
    return s[:maxlen]


def _render_past_line(width: int, positions: List[int]) -> str:
    """Render past zone: ━ with ● at dot positions."""
    if not positions:
        return _DASH * width

    parts: List[str] = []
    prev = 0
    for pos in positions:
        pos = max(0, min(pos, width - 1))
        gap = pos - prev
        if gap > 0:
            parts.append(_DASH * gap)
        parts.append(_DOT)
        prev = pos + 1

    tail = width - prev
    if tail > 0:
        parts.append(_DASH * tail)
    return "".join(parts)


def _render_future_zone(width: int, char: str, has_dot: bool) -> str:
    """Render a future zone, optionally placing a dot at the midpoint."""
    if has_dot and width >= 3:
        half = width // 2
        return char * half + _DOT + char * (width - half - 1)
    return char * width


def render_timeline_rows(
    projects: list[dict], vision_entries, vision_project
) -> List[str]:
    """Paint project timelines; VISION labels stay on their owning checkout."""
    lines = []
    for project in projects:
        if lines:
            lines.append("")
        vision = list(vision_entries) if project["project"] == vision_project else []
        queued = project["queued"]
        past, future = project["past_width"], project["future_width"]
        lines.append(
            _render_pathway(
                project["emoji"],
                past,
                future,
                queued > 0,
                vision,
                len(vision),
                project["positions"],
            )
        )
        lines.append(
            _render_labels(
                project["labels"],
                past,
                future,
                queued > 0,
                queued,
                vision,
                len(vision),
            )
        )
    return lines


def _render_pathway(
    emoji: str,
    past_width: int,
    future_width: int,
    has_queued: bool,
    vision_entries: List[Tuple[str, str]],
    vision_count: int,
    positions: List[int],
) -> str:
    """Render LINE 1: emoji + pathway with zone chars."""
    parts: List[str] = []

    # Emoji prefix
    parts.append(emoji)

    # Past zone
    parts.append(_render_past_line(past_width, positions))

    # Present marker
    parts.append(_PRESENT)

    # Future zones
    if has_queued or vision_entries:
        fzones = (1 if has_queued else 0) + vision_count
        if fzones == 0:
            fzones = 1
        per = future_width // fzones
        if per < 3:
            per = 3

        if has_queued:
            parts.append(_DASHED * per)

        for idx, (_vk, _vl) in enumerate(vision_entries):
            if idx == 0:
                parts.append(_render_future_zone(per, _DOTTED, True))
            elif idx == 1:
                parts.append(_render_future_zone(per, _MIDDLE_DOT, True))
            else:
                parts.append(_render_future_zone(per, _TILDE, True))

    return "".join(parts)


def _render_labels(
    labels: List[str],
    past_width: int,
    future_width: int,
    has_queued: bool,
    queued_count: int,
    vision_entries: List[Tuple[str, str]],
    vision_count: int,
) -> str:
    """Render LINE 2: feature labels + future labels."""
    parts: List[str] = []

    # 4-char indent (aligns with emoji column)
    parts.append("    ")

    # Past zone labels
    printed = 0
    if labels:
        count = len(labels)
        per = past_width // count
        if per < 3:
            per = 3

        for idx, lab in enumerate(labels):
            if per >= 12:
                show = _truncate(lab, 12)
            elif per >= 6:
                show = _truncate(lab, per - 1)
            elif per >= 3:
                show = _truncate(lab, 2)
            else:
                show = "."

            if idx == count - 1:
                # Last label fills remaining past width
                last_w = past_width - printed
                parts.append(show.ljust(last_w))
                printed = past_width
            else:
                parts.append(show.ljust(per))
                printed += per

    # Pad remaining past zone space
    remain = past_width - printed
    if remain > 0:
        parts.append(" " * remain)

    # Present marker spacing (4 cols)
    parts.append("    ")

    # Future labels
    if has_queued or vision_entries:
        fzones = (1 if has_queued else 0) + vision_count
        if fzones == 0:
            fzones = 1
        per_fl = future_width // fzones
        if per_fl < 3:
            per_fl = 3

        if has_queued:
            parts.append(f"{queued_count}q".ljust(per_fl))

        for _vk, vl in vision_entries:
            vs = _truncate(vl, per_fl - 1)
            parts.append(vs.ljust(per_fl))

    return "".join(parts)
