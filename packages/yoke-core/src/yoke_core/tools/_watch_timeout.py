"""Timeout teaching shared by watcher recipes."""

from yoke_contracts.watch_cli_forms import WATCHER_MAX_DURATION_SECONDS


def watcher_timeout_ms(kind: str, args) -> int:
    """Use a fleet watch's declared duration, or the longest wrapper bound."""
    if kind == "fleet":
        from yoke_core.domain.fleet_delta_probe import _parse_args

        duration = _parse_args(args).duration
        if duration > 0:
            return int(duration * 1000)
    return WATCHER_MAX_DURATION_SECONDS * 1000
