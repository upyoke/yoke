"""Project-scoped item reference formatting — pure, client-tier.

A public item ref is ``<public_item_prefix>-<project_sequence>`` (for
example, ``YOK-N``). Hosted in yoke_contracts so the board render (and any client)
can format refs without ``yoke_core``; ``yoke_core.domain.project_identity``
re-exports these for its existing callers.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

DEFAULT_PUBLIC_ITEM_PREFIX = "YOK"

_PUBLIC_REF_RE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9]*)-(?P<seq>\d+)$")
_BARE_SEQUENCE_RE = re.compile(r"^\d+$")


def format_item_ref(
    project_slug: Any,
    public_item_prefix: Any,
    project_sequence: Any,
    *,
    qualify: bool = False,
    item_id: Optional[int] = None,
) -> str:
    del project_slug, qualify
    prefix = str(public_item_prefix or DEFAULT_PUBLIC_ITEM_PREFIX)
    try:
        sequence = int(project_sequence)
    except (TypeError, ValueError):
        sequence = int(item_id) if item_id is not None else 0
    return f"{prefix}-{sequence}"


def parse_public_item_ref(text: Any) -> Tuple[Optional[str], Optional[int]]:
    """Split a reference into its prefix and sequence — the read direction of
    :func:`format_item_ref`.

    Returns ``(prefix, sequence)`` for the full ``PREFIX-N`` form with the
    prefix upper-cased, and ``(None, sequence)`` for a bare ``N``, which names
    a sequence but no project and so only identifies an item once the caller
    supplies one. Free text that is neither shape yields ``(None, None)``.
    """
    candidate = str(text or "").strip()
    if _BARE_SEQUENCE_RE.match(candidate):
        return None, int(candidate)
    match = _PUBLIC_REF_RE.match(candidate)
    if match is None:
        return None, None
    return match.group("prefix").upper(), int(match.group("seq"))
