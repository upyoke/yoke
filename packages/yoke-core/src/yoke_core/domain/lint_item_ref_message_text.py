"""Scanner: message text names an item by reference, never by ``items.id``.

``f"item {item_id} is terminal"`` prints an internal id where a reader sees a
reference, and ``--item {item_id}`` hands one to a command that accepts only
public refs. Both read as an item name and neither is one: ``items.id`` and
``project_sequence`` are independent counters, so the number shown belongs to
whichever other item owns it.

Message text therefore names an item through ``render_item_ref`` (or the
public ref it was already handed). Code that genuinely means the storage key
writes ``items.id {item_id}``, which this scan reads as the label it is and
leaves alone. The companion
:mod:`yoke_core.domain.lint_item_ref_construction` covers the two directions
that do carry a literal ref prefix.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from yoke_core.domain.lint_item_ref_construction import (
    RefLiteralHit,
    SCAN_ROOTS,
    is_exempt_relpath,
)

# This module carries the shape it hunts for, as the docstring example that
# explains it. Anything else added here has to justify itself in a comment.
_ALLOWLIST: frozenset[str] = frozenset(
    {"packages/yoke-core/src/yoke_core/domain/lint_item_ref_message_text.py"}
)


# Prose naming an item, then an interpolation of something id-shaped. The
# lookbehind keeps ``items.id {item_id}`` out: there the word is followed by
# ``.id``, which labels the number as the storage key rather than presenting
# it as a reference.
_PROSE_ITEM_ID_RE = re.compile(
    r"(?<![\w.])(?:[Ii]tem|[Ee]pic)s?[ \t]+\{([^{}]*)\}"
    r"|--(?:item|epic)[ =]\{([^{}]*)\}"
)

# An interpolation naming one of these has already been through the renderer
# (or arrived as a public ref), so the number it prints is a reference.
_RENDERED_REF_TOKENS: Tuple[str, ...] = (
    "_ref",
    "ref_",
    "public_ref",
    "render_item_ref",
    "render_item_refs",
    "render_column_item_ref",
    "item_ref_for_id",
    "unresolved_item_ref",
)


def scan_message_text_item_ids(repo_root: Path) -> List[RefLiteralHit]:
    """Return every internal item id interpolated into message text.

    An f-string is the only shape that can carry one, so the scan reads
    lines that open one and reports the id-shaped interpolations that
    follow the word ``item`` or ``epic`` (or an ``--item`` / ``--epic``
    flag, which accepts public refs only).
    """
    root = repo_root.resolve()
    hits: List[RefLiteralHit] = []
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if is_exempt_relpath(rel) or rel in _ALLOWLIST:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, raw in enumerate(lines, start=1):
                if 'f"' not in raw and "f'" not in raw:
                    continue
                for match in _PROSE_ITEM_ID_RE.finditer(raw):
                    expression = match.group(1) or match.group(2) or ""
                    lowered = expression.lower()
                    if "id" not in lowered:
                        continue
                    if any(token in lowered for token in _RENDERED_REF_TOKENS):
                        continue
                    hits.append(
                        RefLiteralHit(path.resolve(), lineno, raw.strip()[:160])
                    )
    return hits

__all__ = ["scan_message_text_item_ids"]
