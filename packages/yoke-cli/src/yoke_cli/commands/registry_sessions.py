"""Session-family entries for the operations CLI registry."""

from __future__ import annotations

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.sessions_maintenance import (
    sessions_end_if_empty,
    sessions_reclaim_stale,
)


SESSIONS_SUBCOMMAND_REGISTRY = {
    ("sessions", "begin"): ("sessions.begin", _adapters.sessions_begin),
    ("sessions", "init"): ("sessions.init", _adapters.sessions_init),
    ("sessions", "list"): ("sessions.list", _adapters.sessions_list),
    ("sessions", "touch"): ("sessions.touch", _adapters.sessions_touch),
    ("sessions", "checkpoint"): (
        "sessions.checkpoint",
        _adapters.sessions_checkpoint,
    ),
    ("sessions", "checkpoint-read"): (
        "sessions.checkpoint_read",
        _adapters.sessions_checkpoint_read,
    ),
    ("sessions", "offer"): ("sessions.offer", _adapters.sessions_offer),
    ("sessions", "ownership-guard"): (
        "sessions.ownership_guard",
        _adapters.sessions_ownership_guard,
    ),
    ("sessions", "end-if-empty"): (
        "sessions.end_if_empty",
        sessions_end_if_empty,
    ),
    ("sessions", "reclaim-stale"): (
        "sessions.reclaim_stale",
        sessions_reclaim_stale,
    ),
}


__all__ = ["SESSIONS_SUBCOMMAND_REGISTRY"]
