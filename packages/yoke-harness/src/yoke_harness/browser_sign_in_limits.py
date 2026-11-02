"""Sign-in bounds shared with the Chromium authorization window."""

import json
from pathlib import Path

_LIMITS = json.loads(
    (Path(__file__).parent / "browser_runtime/src/authorization-limits.json").read_text(
        encoding="utf-8"
    )
)
AUTHORIZATION_LIMIT_MS = _LIMITS["AUTHORIZATION_LIMIT_MS"]
SHUTDOWN_MS = _LIMITS["SHUTDOWN_MS"]
