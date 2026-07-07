"""Codex model + entrypoint resolution for hook handlers.

Owned separately from the payload module because model resolution
walks the Codex transcript / runtime cache through
``runtime.harness.codex.codex_model``, while payload resolution stays
in /tmp + env-var space.
"""

from __future__ import annotations

import os
from typing import Optional


def resolve_codex_model(payload_model: str = "") -> str:
    """Full Codex model resolution chain.

    Order:
      1. ``YOKE_MODEL`` explicit override
      2. ``CODEX_MODEL`` env var
      3. Payload-provided ``model``
      4. ``runtime.harness.codex.codex_model.resolve()`` (transcript/cache walk)
      5. Literal ``"unknown"``

    Returns a non-empty string so callers can always pass it into
    ``service_client.py session-begin`` without conditional branching.
    """
    yoke_model = os.environ.get("YOKE_MODEL", "")
    if yoke_model:
        return yoke_model
    env_model = os.environ.get("CODEX_MODEL", "")
    if env_model:
        return env_model
    if payload_model:
        return payload_model
    try:
        from runtime.harness.codex.codex_model import resolve as _resolve_model

        model = _resolve_model()
        if model:
            return model
    except Exception:
        pass
    return "unknown"


def resolve_codex_entrypoint() -> Optional[str]:
    """Best-effort Codex entrypoint detection from runtime metadata."""
    try:
        from runtime.harness.codex.codex_model import resolve_entrypoint

        return resolve_entrypoint()
    except Exception:
        return None
