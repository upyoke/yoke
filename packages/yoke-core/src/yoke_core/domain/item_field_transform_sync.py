"""Small sync metadata helpers for item-field transforms."""

from __future__ import annotations

from time import perf_counter

from yoke_core.domain import sections as _sections


def sync_section_body(item_id: int, operation: str) -> tuple[bool, str, str, int]:
    """Sync a section-mutated body and return ``ok, reason, mode, elapsed_ms``."""
    start = perf_counter()
    ok, reason = _sections.sync_body_after_section_mutation(item_id, operation)
    elapsed_ms = int((perf_counter() - start) * 1000)
    if reason:
        mode = "degraded"
    elif ok:
        mode = "ok"
    else:
        mode = "unknown"
    return ok, reason, mode, elapsed_ms


__all__ = ["sync_section_body"]
