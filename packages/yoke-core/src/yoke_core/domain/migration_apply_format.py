"""Console formatting for governed migration rehearse / live-apply results.

The subject label renders the item's public ref (project prefix + project
sequence) via the canonical formatter; itemless manifest runs render as
``manifest``.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.migration_apply_contract import (
    RehearseResult,
)


def _subject(item_id: Optional[int]) -> str:
    if item_id is None:
        return "manifest"
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    try:
        with db_helpers.connect() as conn:
            return render_item_ref(conn, item_id)
    except Exception:  # noqa: BLE001 - display fallback only
        from yoke_contracts.item_ref import DEFAULT_PUBLIC_ITEM_PREFIX

        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{item_id}"


def format_rehearse(
    result: RehearseResult,
) -> str:
    lines = [
        f"rehearse {_subject(result.item_id)} model={result.model_name} "
        f"validation_db={result.validation_db_path}",
    ]
    extra = ""
    if extra is not None:
        lines.append(extra)
    for mod in result.modules:
        lines.append(
            f"  {mod.identifier}: state={mod.state}"
            + (f" ERROR={mod.error}" if mod.error else "")
        )
    if result.source_fingerprint:
        lines.append(
            f"  source_fingerprint={result.source_fingerprint[:16]}... "
            f"rehearsed_at={result.rehearsed_at}"
        )
    return "\n".join(lines)


__all__ = ["format_rehearse"]
