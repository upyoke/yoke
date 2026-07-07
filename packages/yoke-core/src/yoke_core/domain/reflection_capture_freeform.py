"""Freeform fallback parser + canonical-entry error collector.

Two responsibilities, both rehomed here to keep
:mod:`yoke_core.domain.reflection_capture_shape_parsers` under the
350-line authored-file cap:

* :func:`try_shape_freeform_multi` — multi-entry freeform parser for blocks
  whose entries are separated by ``---END ENTRY---`` and open with either
  ``UPPERCASE_CATEGORY:`` head or ``category:`` head (no
  ``---BEGIN ENTRY---`` framing).
* :func:`collect_shape_a_errors` — per-entry error collector for
  canonical-shape entries that fail validation (missing ``category``
  field or empty body). Preserves the legacy error-reporting behavior
  callers expect.
* :func:`freeform_block_has_end_markers_no_heads` — backstop helper for
  blocks carrying ``---END ENTRY---`` separators but no parseable heads.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional

from yoke_core.domain.reflection_capture_shape_parsers import ReflectionEntry


FREEFORM_END_RE = re.compile(r"^---END ENTRY---\s*$", re.MULTILINE)
_FREEFORM_UPPERCASE_HEAD_RE = re.compile(r"^([A-Z][A-Z0-9_]+)\s*:\s*(.*)$")
_CATEGORY_HEAD_RE = re.compile(r"^category\s*:\s*(.+)$", re.IGNORECASE)
_SHAPE_A_ENTRY_RE = re.compile(
    r"---BEGIN ENTRY---\s*\n(.*?)\n\s*---END ENTRY---",
    re.DOTALL,
)
_CANONICAL_FIELD_RE = re.compile(
    r"^(timestamp|agent|context|category)\s*:\s*(.+)$",
    re.MULTILINE,
)
_MARKDOWN_HEADER_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
_BOLD_HEADER_LINE_RE = re.compile(r"^\*\*([^*]+?):\*\*\s*$", re.MULTILINE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_category(raw: str) -> str:
    out = raw.strip().lower().rstrip(":")
    return re.sub(r"[\s_]+", "-", out)


def _parse_freeform_segment(seg: str, default_agent: str) -> Optional[ReflectionEntry]:
    stripped = seg.lstrip("\n").rstrip()
    if not stripped:
        return None
    lines = stripped.split("\n")
    first_idx = 0
    while first_idx < len(lines) and not lines[first_idx].strip():
        first_idx += 1
    if first_idx >= len(lines):
        return None
    first_line = lines[first_idx]
    rest = lines[first_idx + 1:]
    cat_match = _CATEGORY_HEAD_RE.match(first_line)
    if cat_match:
        category = _normalize_category(cat_match.group(1).strip())
        body = "\n".join(rest).strip()
        if not body or not category:
            return None
        return ReflectionEntry(
            timestamp=_now_iso(), agent=default_agent, context="",
            category=category, body=body,
        )
    upper_head = _FREEFORM_UPPERCASE_HEAD_RE.match(first_line)
    if upper_head:
        body_parts: list[str] = []
        inline_body = upper_head.group(2).strip()
        if inline_body:
            body_parts.append(inline_body)
        body_parts.extend(rest)
        body = "\n".join(body_parts).strip()
        if not body:
            return None
        category = _normalize_category(upper_head.group(1))
        return ReflectionEntry(
            timestamp=_now_iso(), agent=default_agent, context="",
            category=category, body=body,
        )
    return None


def try_shape_freeform_multi(
    block: str, default_agent: str,
) -> Optional[List[ReflectionEntry]]:
    """Multi-entry freeform fallback: segments separated by ``---END ENTRY---``.

    Each segment opens with either ``UPPERCASE:`` head or
    ``category:`` head. Handles the historical freeform shape that
    pre-dates the canonical ``---BEGIN ENTRY--- / ---END ENTRY---``
    framing.
    """
    if not FREEFORM_END_RE.search(block):
        return None
    segments = FREEFORM_END_RE.split(block)
    if len(segments) < 2:
        return None
    parsed: list[ReflectionEntry] = []
    for seg in segments[:-1]:
        entry = _parse_freeform_segment(seg, default_agent)
        if entry is not None:
            parsed.append(entry)
    return parsed if parsed else None


def freeform_block_has_end_markers_no_heads(block: str) -> bool:
    """True when a block carries ``---END ENTRY---`` separators but no parseable heads."""
    if not FREEFORM_END_RE.search(block):
        return False
    segments = FREEFORM_END_RE.split(block)
    for seg in segments[:-1]:
        if _parse_freeform_segment(seg, "unknown") is not None:
            return False
    return True


def _split_by_header_re(block: str, header_re: re.Pattern) -> List[tuple[str, str]]:
    """Return ``[(category, body), ...]`` segments split on header_re matches.

    Only fires when the block starts with the header pattern; otherwise
    we'd happily grab arbitrary prose. Category is derived from the
    header match group; body is everything from after that header line
    to the next header (or end of block).
    """
    stripped = block.lstrip()
    if not header_re.match(stripped):
        return []
    headers = list(header_re.finditer(block))
    if not headers:
        return []
    out: list[tuple[str, str]] = []
    for i, h in enumerate(headers):
        raw_cat = h.group(1).strip()
        category = _normalize_category(raw_cat.split(":")[0])
        if not category:
            continue
        body_start = h.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(block)
        body = block[body_start:body_end].strip()
        if body:
            out.append((category, body))
    return out


def try_shape_markdown_freeform(
    block: str, default_agent: str,
) -> Optional[List[ReflectionEntry]]:
    """Block opens with a ``#``/``##``/``###`` markdown header; sections become entries."""
    segments = _split_by_header_re(block, _MARKDOWN_HEADER_RE)
    if not segments:
        return None
    return [ReflectionEntry(
        timestamp=_now_iso(), agent=default_agent, context="",
        category=cat, body=body,
    ) for cat, body in segments]


def try_shape_bold_header_freeform(
    block: str, default_agent: str,
) -> Optional[List[ReflectionEntry]]:
    """Block opens with a ``**Header:**`` bold-emphasized header line; sections become entries."""
    segments = _split_by_header_re(block, _BOLD_HEADER_LINE_RE)
    if not segments:
        return None
    return [ReflectionEntry(
        timestamp=_now_iso(), agent=default_agent, context="",
        category=cat, body=body,
    ) for cat, body in segments]


def try_shape_generic_freeform(
    block: str, default_agent: str,
) -> Optional[List[ReflectionEntry]]:
    """Last-resort: capture any non-empty REFLECTION-bounded block as one ``freeform`` entry.

    Skips canonical ``---BEGIN ENTRY---`` framing, which is shape A's
    territory — malformed canonical entries surface as orchestrator
    errors instead of being silently flattened. All other unrecognized
    REFLECTION-bounded content is captured rather than dropped, since
    the subagent intentionally bounded it.
    """
    body = block.strip()
    if not body:
        return None
    if _SHAPE_A_ENTRY_RE.search(block):
        return None
    return [ReflectionEntry(
        timestamp=_now_iso(), agent=default_agent, context="",
        category="freeform", body=body,
    )]


_OBSERVATION_BODY_PREFIX_RE = re.compile(r"^observation\s*:\s*", re.IGNORECASE)


def collect_shape_a_errors(block: str) -> List[str]:
    """Per-entry errors for canonical-shape entries that fail validation.

    Honors the ``observation:`` body-prefix fallback that
    :func:`yoke_core.domain.reflection_capture_shape_parsers._parse_canonical_entry`
    accepts as an implicit category; if observation supplies the
    category, the entry is parseable and no error is emitted.
    """
    errors: list[str] = []
    raw_entries = _SHAPE_A_ENTRY_RE.findall(block)
    for idx, raw in enumerate(raw_entries, 1):
        fields: dict[str, str] = {}
        for m in _CANONICAL_FIELD_RE.finditer(raw):
            fields[m.group(1)] = m.group(2).strip()
        body_lines: list[str] = []
        past_fields = False
        for line in raw.split("\n"):
            if not past_fields and _CANONICAL_FIELD_RE.match(line):
                continue
            if not past_fields and line.strip() == "---":
                past_fields = True
                continue
            past_fields = True
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        category = fields.get("category")
        if not category and body and _OBSERVATION_BODY_PREFIX_RE.match(body):
            category = "observation"
        if not category:
            errors.append(f"Entry #{idx}: missing required 'category' field")
            continue
        if not body:
            errors.append(f"Entry #{idx}: empty body text")
    return errors


__all__ = [
    "FREEFORM_END_RE",
    "collect_shape_a_errors",
    "freeform_block_has_end_markers_no_heads",
    "try_shape_bold_header_freeform",
    "try_shape_freeform_multi",
    "try_shape_generic_freeform",
    "try_shape_markdown_freeform",
]
