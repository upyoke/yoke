"""Shared primitives for advance skip flows."""

from __future__ import annotations

import os
from typing import TextIO


_POLISH_START = "reviewed-implementation"
_POLISH_TRANSIT = "polishing-implementation"
_POLISH_END = "implemented"

_REFINE_ROUTING: dict[str, tuple[list[str], str]] = {
    "idea": (["refining-idea", "refined-idea"], "refining-idea"),
    "refining-idea": (["refined-idea"], "refining-idea"),
    "plan-drafted": (["refining-plan", "planned"], "refining-plan"),
    "refining-plan": (["planned"], "refining-plan"),
}

BYPASS_SKIP_POLISH = "skip-polish"
BYPASS_SKIP_REFINE = "skip-refine"

_POLISH_TRANSIT_ALLOWED: frozenset[str] = frozenset({_POLISH_TRANSIT, _POLISH_END})
_REFINE_TARGETS_ALLOWED: frozenset[str] = frozenset(
    status
    for hops, _skipped_phase in _REFINE_ROUTING.values()
    for status in hops
)


def _lookup_item(item_id: int) -> tuple[str, str]:
    """Return (current_status, item_type) for *item_id*."""
    from yoke_core.domain.backlog_queries import _resolve_write_db_path
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect

    db_path = _resolve_write_db_path()
    conn = connect(db_path)
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status, type FROM items WHERE id = {p}", (item_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"Item YOK-{item_id} not found")
    return row["status"], row["type"]


def _do_execute_update(
    item_id: int,
    status: str,
    out: TextIO,
    *,
    rebuild_board: bool = True,
) -> dict:
    """Run ``backlog.execute_update`` for a single status hop."""
    from yoke_core.domain.backlog import execute_update

    return execute_update(
        item_id=item_id,
        field="status",
        value=status,
        rebuild_board=rebuild_board,
        out=out,
    )


def _walk_hops(
    item_id: int,
    hops: list[str],
    *,
    bypass_reason: str,
    allowlist: frozenset[str],
    out: TextIO,
) -> list[str]:
    """Walk *hops* with scoped YOKE_CLAIM_BYPASS and YOKE_STATUS_SOURCE."""
    for status in hops:
        if status not in allowlist:
            raise ValueError(
                f"Skip hop to {status!r} is not in allowlist for reason "
                f"{bypass_reason!r} - refusing to bypass claim verification."
            )

    prev_bypass = os.environ.get("YOKE_CLAIM_BYPASS")
    prev_source = os.environ.get("YOKE_STATUS_SOURCE")

    os.environ["YOKE_CLAIM_BYPASS"] = bypass_reason
    os.environ["YOKE_STATUS_SOURCE"] = bypass_reason

    written: list[str] = []
    try:
        for idx, status in enumerate(hops):
            result = _do_execute_update(
                item_id,
                status,
                out,
                rebuild_board=(idx == len(hops) - 1),
            )
            if not result.get("success"):
                error = result.get("error", "unknown error")
                raise RuntimeError(f"Skip hop to {status!r} failed: {error}")
            written.append(status)
    finally:
        if prev_bypass is None:
            os.environ.pop("YOKE_CLAIM_BYPASS", None)
        else:
            os.environ["YOKE_CLAIM_BYPASS"] = prev_bypass
        if prev_source is None:
            os.environ.pop("YOKE_STATUS_SOURCE", None)
        else:
            os.environ["YOKE_STATUS_SOURCE"] = prev_source

    return written
