"""Deployment-run label resolution."""

from __future__ import annotations

from yoke_core.domain.db_helpers import connect


def item_label(first_item: str) -> str:
    """Public item ref for ephemeral tracking, or empty for item-less runs."""
    if not first_item:
        return ""
    from yoke_core.domain.project_identity import render_item_ref

    conn = connect()
    try:
        return render_item_ref(conn, int(first_item))
    except Exception:
        return str(first_item)
    finally:
        conn.close()


__all__ = ["item_label"]
