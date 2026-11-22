"""The marker a setup process hands the process it re-runs after a release follow.

Setup re-runs itself on a freshly installed release either before it asks
anything (the start check) or as ``yoke setup --resume RUN-ID`` after Apply met
a different served release. The new process reads this marker to record
``cli_followed_release`` in its run report and to follow at most once.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

FOLLOWED_RELEASE_ENV = "YOKE_SETUP_FOLLOWED_RELEASE"


def encode(running: str, served: str, run_id: str = "") -> str:
    return json.dumps({"from": running, "to": served, "run_id": run_id}, sort_keys=True)


def current() -> dict[str, str] | None:
    """The follow this process was started by, or None."""
    raw = os.environ.get(FOLLOWED_RELEASE_ENV)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not value.get("to"):
        return None
    return {key: str(value.get(key) or "") for key in ("from", "to", "run_id")}


def recorded(resume_payload: Mapping[str, Any] | None) -> dict[str, str] | None:
    """``cli_followed_release`` for a run report: the resumed run's, else this one's."""
    prior = (resume_payload or {}).get("cli_followed_release")
    if isinstance(prior, Mapping) and prior.get("to"):
        return {"from": str(prior.get("from") or ""), "to": str(prior["to"])}
    marker = current()
    return {"from": marker["from"], "to": marker["to"]} if marker else None


__all__ = ["FOLLOWED_RELEASE_ENV", "current", "encode", "recorded"]
