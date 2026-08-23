"""Observed machine and harness-version facts for session registration."""

from __future__ import annotations

import os
from typing import Mapping, Optional

from yoke_contracts.machine_config.runtime import ensure_machine_id
from yoke_contracts.executor_labels import canonical_harness_id


_VERSION_ENV_BY_EXECUTOR = {
    "claude-code": (
        "CLAUDE_CODE_VERSION",
        "CLAUDE_VERSION",
    ),
    "codex": (
        "CODEX_VERSION",
        "CODEX_CLI_VERSION",
        "CHATGPT_VERSION",
    ),
    "cursor": (
        "CURSOR_VERSION",
        "CURSOR_AGENT_VERSION",
    ),
}


def client_executor_version(
    executor: str,
    *,
    executor_surface: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Optional[str]:
    """Return a client-observed version without launching vendor clients."""
    env = os.environ if environ is None else environ
    explicit = str(env.get("YOKE_EXECUTOR_VERSION") or "").strip()
    if explicit:
        return explicit
    family = canonical_harness_id(executor)
    for key in _VERSION_ENV_BY_EXECUTOR.get(family, ()):
        value = str(env.get(key) or "").strip()
        if value:
            return value
    surface = str(executor_surface or "").strip()
    if surface.endswith("-desktop"):
        try:
            from yoke_harness.session_relay_inventory import probe_surface_version

            return probe_surface_version(surface)
        except Exception:  # noqa: BLE001 - observed identity is best effort
            return None
    return None


def client_machine_id() -> Optional[str]:
    """Return the stable machine UUID, initializing configured machines."""
    try:
        return ensure_machine_id()
    except Exception:  # noqa: BLE001 - identity enrichment is best effort
        return None


__all__ = ["client_executor_version", "client_machine_id"]
