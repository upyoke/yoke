"""Best-effort backlog rendering after a GitHub item sync."""

from __future__ import annotations

import sys


def regenerate_item_markdown(item_id: str) -> None:
    """Regenerate the local item document when the reference is numeric."""
    try:
        item_id_int = int(str(item_id).lstrip("#"))
    except ValueError:
        return
    try:
        from yoke_core.domain import backlog as backlog_domain

        backlog_domain._generate_md(item_id_int, out=sys.stderr)
    except Exception:  # pragma: no cover - rendering is best effort
        return
