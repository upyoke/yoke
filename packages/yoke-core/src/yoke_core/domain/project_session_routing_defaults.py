"""Default ``session-routing`` capability settings.

Split from :mod:`project_policy_capabilities` under the authored-file
line limit so project-policy can own nested board settings without
growing that module past the cap.
"""

from __future__ import annotations

import copy
from typing import Any

from yoke_contracts.session_level import DEFAULT_LEVEL_METADATA

_SESSION_ROUTING_DEFAULTS: dict[str, Any] = {
    "executor_default_levels": {
        "claude*": "DARIUS",
        "codex*": "ALTMAN",
        "DARIUS": "DARIUS",
        "ALTMAN": "ALTMAN",
    },
    "level_metadata": DEFAULT_LEVEL_METADATA,
}


def session_routing_defaults() -> dict[str, Any]:
    """Return default ``session-routing`` settings."""

    return copy.deepcopy(_SESSION_ROUTING_DEFAULTS)


__all__ = ["session_routing_defaults"]
