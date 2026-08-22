"""Usage catalog for session and frontier commands."""

from yoke_cli.commands.adapters.frontier_read import FRONTIER_LIST_USAGE
from yoke_cli.commands.adapters.sessions import (
    CHARGE_SCHEDULE_USAGE,
    SESSIONS_BEGIN_USAGE,
    SESSIONS_CHECKPOINT_READ_USAGE,
    SESSIONS_CHECKPOINT_USAGE,
    SESSIONS_IDENTITY_USAGE,
    SESSIONS_OFFER_USAGE,
    SESSIONS_OWNERSHIP_GUARD_USAGE,
    SESSIONS_TOUCH_USAGE,
)
from yoke_cli.commands.adapters.sessions_maintenance import (
    SESSIONS_END_IF_EMPTY_USAGE,
    SESSIONS_RECLAIM_STALE_USAGE,
)
from yoke_cli.commands.adapters.sessions_read import SESSIONS_LIST_USAGE
from yoke_cli.commands.adapters.session_control_usage import (
    SESSION_CONTROL_USAGE_BY_FUNCTION_ID,
)


USAGE_BY_FUNCTION_ID = {
    "sessions.begin": SESSIONS_BEGIN_USAGE,
    "sessions.identity": SESSIONS_IDENTITY_USAGE,
    "sessions.list": SESSIONS_LIST_USAGE,
    "sessions.touch": SESSIONS_TOUCH_USAGE,
    "sessions.checkpoint": SESSIONS_CHECKPOINT_USAGE,
    "sessions.checkpoint_read": SESSIONS_CHECKPOINT_READ_USAGE,
    "sessions.offer": SESSIONS_OFFER_USAGE,
    "sessions.ownership_guard": SESSIONS_OWNERSHIP_GUARD_USAGE,
    "sessions.end_if_empty": SESSIONS_END_IF_EMPTY_USAGE,
    "sessions.reclaim_stale": SESSIONS_RECLAIM_STALE_USAGE,
    "charge.schedule": CHARGE_SCHEDULE_USAGE,
    "frontier.list": FRONTIER_LIST_USAGE,
    **SESSION_CONTROL_USAGE_BY_FUNCTION_ID,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
