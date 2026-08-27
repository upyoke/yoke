"""Default ``session-routing`` capability settings.

Split from :mod:`project_policy_capabilities` under the authored-file
line limit so project-policy can own nested board settings without
growing that module past the cap.
"""

from __future__ import annotations

import copy
from typing import Any

from yoke_contracts.session_lane import DEFAULT_LANE_METADATA

_SESSION_ROUTING_DEFAULTS: dict[str, Any] = {
    "executor_default_lanes": {
        "claude*": "DARIUS",
        "codex*": "ALTMAN",
        "DARIUS": "DARIUS",
        "ALTMAN": "ALTMAN",
    },
    "lane_paths": {
        "DARIUS": [
            "shepherd",
            "advance",
            "conduct",
            "dash",
            "blitz",
            "refine",
            "polish",
            "usher",
            "strategize",
            "feed",
            "steer",
            "doctor",
        ],
        "ALTMAN": [
            "refine",
            "polish",
            "usher",
            "dash",
        ],
    },
    "lane_metadata": DEFAULT_LANE_METADATA,
    "process_offers": {
        "default": False,
        "strategize": False,
        "feed": False,
        "doctor": False,
    },
}


def session_routing_defaults() -> dict[str, Any]:
    """Return default ``session-routing`` settings."""

    return copy.deepcopy(_SESSION_ROUTING_DEFAULTS)


__all__ = ["session_routing_defaults"]
