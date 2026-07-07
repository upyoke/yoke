"""Title-only body heuristic for ``status='idea'`` items.

Single source of truth for the slack-bounded "body is title-only"
classification used by:

- :mod:`yoke_core.domain.frontier_compute` — pushes incomplete idea
  bodies into ``blocked`` instead of ``runnable`` so the frontier never
  hands a title-only ticket to ``/yoke refine``.
- :mod:`yoke_core.engines.doctor_hc_meta_backlog` — surfaces tail-case
  items that re-emerged unclaimed after stale-heartbeat reclaim.
- ``.agents/skills/yoke/advance/preflight-recovery.md`` — the
  reconciliation gate's advisory shares this heuristic.

The slack constant lives here so the three consumers cannot drift out of
agreement.
"""

from __future__ import annotations

from typing import Mapping, Optional


IDEA_BODY_SLACK = 4
"""Bytes of allowed wiggle room past the rendered title-header line.

Mirrors the shell heuristic in
``.agents/skills/yoke/advance/preflight-recovery.md`` step 3:
``body_len <= title_header_len + 4`` flags the body as title-only.
"""

INCOMPLETE_REASON = "idea-incomplete"
"""Token surfaced in ``blocked_reasons`` when the heuristic fires."""


def title_header_length(title: str) -> int:
    """Return the byte length of the rendered ``# {title}`` heading."""
    if not title:
        return 0
    return len(("# " + title).encode("utf-8"))


def _coerce_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return str(value)


def is_idea_body_incomplete(item_row: Mapping[str, object]) -> bool:
    """Return True when the row's spec/body is at most title-only.

    Accepts either a sqlite3.Row or a plain mapping. Reads the rendered
    body from ``spec`` first (the structured field that backs the virtual
    body) and falls back to a ``body`` key when callers pass a
    pre-rendered row.
    """
    title = _coerce_text(item_row.get("title") if hasattr(item_row, "get") else item_row["title"])
    spec = _coerce_text(_safe_get(item_row, "spec"))
    body = spec if spec else _coerce_text(_safe_get(item_row, "body"))
    if not body.strip():
        return True
    body_bytes = len(body.encode("utf-8"))
    return body_bytes <= title_header_length(title) + IDEA_BODY_SLACK


def _safe_get(item_row: Mapping[str, object], key: str) -> Optional[object]:
    if hasattr(item_row, "get"):
        return item_row.get(key)
    try:
        return item_row[key]
    except (KeyError, IndexError):
        return None


__all__ = [
    "IDEA_BODY_SLACK",
    "INCOMPLETE_REASON",
    "is_idea_body_incomplete",
    "title_header_length",
]
