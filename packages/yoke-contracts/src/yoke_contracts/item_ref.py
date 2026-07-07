"""Project-scoped item reference formatting — pure, client-tier.

A public item ref is ``<public_item_prefix>-<project_sequence>`` (for
example, ``YOK-N``). Hosted in yoke_contracts so the board render (and any client)
can format refs without ``yoke_core``; ``yoke_core.domain.project_identity``
re-exports these for its existing callers.
"""

from __future__ import annotations

from typing import Any, Optional

DEFAULT_PUBLIC_ITEM_PREFIX = "YOK"


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
