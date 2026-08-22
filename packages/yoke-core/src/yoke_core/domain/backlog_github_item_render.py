"""Best-effort backlog rendering after a GitHub item sync."""

from __future__ import annotations

import sys


def regenerate_item_markdown(item_id: int) -> None:
    """Regenerate the local item document for a resolved internal id."""
    try:
        from yoke_core.domain import backlog as backlog_domain

        backlog_domain._generate_md(item_id, out=sys.stderr)
    except Exception:  # pragma: no cover - rendering is best effort
        return
