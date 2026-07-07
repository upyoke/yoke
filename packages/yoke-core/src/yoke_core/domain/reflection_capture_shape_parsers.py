"""Shape-specific entry parsers for :mod:`reflection_capture_shapes`.

Each ``try_shape_*`` helper parses one block under one of the documented
reflection shapes; returns ``None`` when the shape does not match. The
orchestrator in :mod:`reflection_capture_shapes` chains them in priority
order and stops at the first shape that yields entries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class ReflectionEntry:
    """One parsed reflection entry; defined here so orchestrator + CLI import without cycles."""
    timestamp: str
    agent: str
    context: str
    category: str
    body: str


_SHAPE_A_ENTRY_RE = re.compile(
    r"---BEGIN ENTRY---\s*\n(.*?)\n\s*---END ENTRY---",
    re.DOTALL,
)
_SHAPE_B_ENTRY_RE = re.compile(
    r"---ENTRY---\s*\n(.*?)\n\s*---END ENTRY---",
    re.DOTALL,
)
_SHAPE_C_HEADER_RE = re.compile(r"^ENTRY[\s-]+\d+\s*$", re.MULTILINE)
_SHAPE_C_END_RE = re.compile(r"^---END ENTRY---\s*$", re.MULTILINE)
_SHAPE_D_HEADER_RE = re.compile(r"^\*\*Entry\s+\d+\*\*\s*$", re.MULTILINE)
_SHAPE_E_OPENER_RE = re.compile(r"^---ENTRY-START---\s*$", re.MULTILINE)
_SHAPE_G_HEADER_RE = re.compile(r"^ENTRY:\s+\S.*$", re.MULTILINE)

_CANONICAL_FIELD_RE = re.compile(
    r"^(timestamp|agent|context|category)\s*:\s*(.+)$",
    re.MULTILINE,
)
_CATEGORY_KEY_RE = re.compile(
    r"^category\s*:\s*(\S+.*)$", re.IGNORECASE | re.MULTILINE,
)
_KIND_FIELD_RE = re.compile(
    r"^kind\s*:\s*(\S+.*)$", re.IGNORECASE | re.MULTILINE,
)
_UPPERCASE_FIELD_RE = re.compile(r"^([A-Z][A-Z0-9_]+)\s*:\s*(.+)$", re.MULTILINE)
_BULLET_FIELD_RE = re.compile(r"^[-*]\s+\*\*([^*]+):\*\*\s*(.+)$", re.MULTILINE)
_TYPE_FIELD_RE = re.compile(r"^type\s*:\s*(\S+.*)$", re.IGNORECASE | re.MULTILINE)
_SINGULAR_FIELD_RE = re.compile(
    r"^(agent|context|category|timestamp|severity|title|impact|type)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_BOLD_FIELD_LINE_RE = re.compile(
    r"^\*\*([A-Za-z][A-Za-z _]*):\*\*\s*(.*)$",
    re.MULTILINE,
)
_TYPED_FIELD_RE = re.compile(
    r"^(severity|title|summary|where|evidence|why it matters|fix idea|"
    r"detail|impact|proposed_fix|category)\s*:\s*(.+)$",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_category(raw: str) -> str:
    out = raw.strip().lower().rstrip(":")
    return re.sub(r"[\s_]+", "-", out)


def _split_by_header(
    block: str, header_re: re.Pattern, end_re: Optional[re.Pattern],
) -> List[str]:
    """Split a block into entry segments by header (and optional end-marker) lines."""
    starts = [m.start() for m in header_re.finditer(block)]
    if not starts:
        return []
    segments: list[str] = []
    for i, start in enumerate(starts):
        next_start = starts[i + 1] if i + 1 < len(starts) else len(block)
        seg = block[start:next_start]
        if end_re is not None:
            end_match = end_re.search(seg)
            if end_match:
                seg = seg[: end_match.start()]
        seg_lines = seg.split("\n")
        if seg_lines:
            seg = "\n".join(seg_lines[1:])
        segments.append(seg.strip())
    return segments


_OBSERVATION_BODY_PREFIX_RE = re.compile(r"^observation\s*:\s*", re.IGNORECASE)


def _parse_canonical_entry(raw: str, default_agent: str) -> Optional[ReflectionEntry]:
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
    if not category or not body:
        return None
    return _make_entry(category, body, default_agent, fields)


def _normalize_bold_field_lines(raw: str) -> str:
    """Rewrite ``**Field:** value`` into ``field: value`` for downstream field matching."""
    return _BOLD_FIELD_LINE_RE.sub(
        lambda m: f"{m.group(1).strip().lower().replace(' ', '_')}: {m.group(2)}",
        raw,
    )


def _make_entry(
    category: str, body: str, default_agent: str,
    fields: Optional[dict] = None,
) -> ReflectionEntry:
    f = fields or {}
    return ReflectionEntry(
        timestamp=f.get("timestamp", _now_iso()),
        agent=f.get("agent", default_agent),
        context=f.get("context", ""),
        category=_normalize_category(category),
        body=body,
    )


def _parse_singular_entry(raw: str, default_agent: str) -> Optional[ReflectionEntry]:
    raw = _normalize_bold_field_lines(raw)
    fields: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False
    for line in raw.split("\n"):
        stripped = line.strip()
        if not in_body and stripped.startswith("body:"):
            in_body = True
            tail = stripped[len("body:"):].strip()
            if tail and tail != "|":
                body_lines.append(tail)
            continue
        if in_body:
            body_lines.append(line)
            continue
        m = _SINGULAR_FIELD_RE.match(stripped)
        if m:
            fields[m.group(1).lower()] = m.group(2).strip()
            continue
        if stripped:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    category = fields.get("category") or fields.get("type") or fields.get("title", "")
    if not category or not body:
        return None
    return _make_entry(category, body, default_agent, fields)


def _parse_typed_entry(raw: str, default_agent: str) -> Optional[ReflectionEntry]:
    """Shape C: type: + summary: + where: + evidence: + why it matters: + fix idea:"""
    raw = _normalize_bold_field_lines(raw)
    fields: dict[str, str] = {}
    body_parts: list[str] = []
    type_match = _TYPE_FIELD_RE.search(raw)
    if type_match:
        fields["type"] = type_match.group(1).strip()
    for line in raw.split("\n"):
        m = _TYPED_FIELD_RE.match(line.strip())
        if m:
            key = m.group(1).lower()
            val = m.group(2).strip()
            fields[key] = val
            body_parts.append(f"{key}: {val}")
        elif line.strip() and not _TYPE_FIELD_RE.match(line.strip()):
            body_parts.append(line)
    category = fields.get("category") or fields.get("type")
    body = "\n".join(body_parts).strip()
    if not category or not body:
        return None
    return _make_entry(category, body, default_agent)


def _parse_bullet_entry(raw: str, default_agent: str) -> Optional[ReflectionEntry]:
    """Shape D: - **Observation:** body / - **Process improvement:** body bullets."""
    fields: dict[str, str] = {}
    for m in _BULLET_FIELD_RE.finditer(raw):
        key = m.group(1).strip().lower().replace(" ", "-")
        val = m.group(2).strip()
        fields[key] = val
    if not fields:
        return None
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    category = "observation" if "observation" in fields else next(iter(fields), "freeform")
    return _make_entry(category, body, default_agent)


def _parse_uppercase_entry(raw: str, default_agent: str) -> Optional[ReflectionEntry]:
    """Shape G: OBSERVATION: / CATEGORY: / IMPROVEMENT: uppercase fields."""
    fields: dict[str, str] = {}
    for m in _UPPERCASE_FIELD_RE.finditer(raw):
        fields[m.group(1).lower()] = m.group(2).strip()
    if not fields:
        return None
    category = fields.get("category") or "observation"
    body_parts = [f"{k}: {v}" for k, v in fields.items() if k != "category"]
    body = "\n".join(body_parts) if body_parts else raw.strip()
    if not body:
        return None
    return _make_entry(category, body, default_agent)


def _filter_entries(
    parts: List[str], parser, default_agent: str,
) -> Optional[List[ReflectionEntry]]:
    valid = [e for e in (parser(p, default_agent) for p in parts) if e is not None]
    return valid if valid else None


def try_shape_a(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    return _filter_entries(_SHAPE_A_ENTRY_RE.findall(block), _parse_canonical_entry, default_agent)


def try_shape_b(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    return _filter_entries(_SHAPE_B_ENTRY_RE.findall(block), _parse_singular_entry, default_agent)


def try_shape_c(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    if not _SHAPE_C_HEADER_RE.search(block) or not _SHAPE_C_END_RE.search(block):
        return None
    return _filter_entries(
        _split_by_header(block, _SHAPE_C_HEADER_RE, _SHAPE_C_END_RE),
        _parse_typed_entry, default_agent,
    )


def try_shape_d(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    if not _SHAPE_D_HEADER_RE.search(block):
        return None
    return _filter_entries(
        _split_by_header(block, _SHAPE_D_HEADER_RE, None),
        _parse_bullet_entry, default_agent,
    )


def try_shape_e(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    if not _SHAPE_E_OPENER_RE.search(block):
        return None
    parts = (_split_by_header(block, _SHAPE_E_OPENER_RE, _SHAPE_C_END_RE)
             or _split_by_header(block, _SHAPE_E_OPENER_RE, None))
    return _filter_entries(parts, _parse_singular_entry, default_agent) if parts else None


def try_shape_g(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    if not _SHAPE_G_HEADER_RE.search(block):
        return None
    return _filter_entries(
        _split_by_header(block, _SHAPE_G_HEADER_RE, None),
        _parse_uppercase_entry, default_agent,
    )


def try_shape_f_or_h(block: str, default_agent: str) -> Optional[List[ReflectionEntry]]:
    """Shapes F/H (direct fields). ``type:`` / ``kind:`` are accepted as category aliases."""
    # Canonical framing is shape A's territory — never absorb a malformed
    # canonical block here, since shape A's error reporting depends on
    # the orchestrator seeing no entries.
    if _SHAPE_A_ENTRY_RE.search(block):
        return None
    cat_match = _CATEGORY_KEY_RE.search(block)
    alias_re: Optional[re.Pattern] = None
    for alias in (_TYPE_FIELD_RE, _KIND_FIELD_RE):
        if cat_match:
            break
        cat_match = alias.search(block)
        alias_re = alias
    if not cat_match:
        return None
    raw_cat = cat_match.group(1).strip().split()[0]
    category = _normalize_category(raw_cat)
    body_lines: list[str] = []
    for line in block.split("\n"):
        stripped = line.strip()
        if _CATEGORY_KEY_RE.match(stripped):
            continue
        if alias_re is not None and alias_re.match(stripped):
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()
    if not body or not category:
        return None
    return [_make_entry(category, body, default_agent)]


def get_shape_parsers_in_priority() -> tuple:
    """Priority-ordered shape parser chain; freeform helpers imported lazily to avoid a cycle."""
    from yoke_core.domain.reflection_capture_freeform import (
        try_shape_bold_header_freeform,
        try_shape_freeform_multi,
        try_shape_generic_freeform,
        try_shape_markdown_freeform,
    )
    return (
        try_shape_a, try_shape_b, try_shape_c, try_shape_e,
        try_shape_g, try_shape_d, try_shape_freeform_multi,
        try_shape_markdown_freeform, try_shape_bold_header_freeform,
        try_shape_f_or_h, try_shape_generic_freeform,
    )


__all__ = [
    "get_shape_parsers_in_priority",
    "try_shape_a", "try_shape_b", "try_shape_c", "try_shape_d",
    "try_shape_e", "try_shape_g", "try_shape_f_or_h",
]
