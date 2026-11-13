"""Keep printed command recipes on the active connection."""

import re
import shlex

_YOKE_CALL = re.compile(r"(^|\$\()yoke ")


def _with_env(command: str) -> str:
    """Pin printed recipes to the active connection."""
    from yoke_cli.config.machine_config import active_env

    try:
        env = active_env()
    except Exception:  # noqa: BLE001 - an unreadable config keeps the bare recipe
        return command
    if not env:
        return command
    return _YOKE_CALL.sub(
        lambda m: f"{m.group(1)}yoke --env {shlex.quote(env)} ", command
    )
