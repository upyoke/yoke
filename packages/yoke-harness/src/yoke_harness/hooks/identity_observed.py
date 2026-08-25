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
_HOOK_SURFACE_PROBE_TIMEOUT_SECONDS = 1.0


def _hook_surface_probe(surface: str):
    """Probe one surface without exceeding a hook's latency budget."""
    from yoke_harness.session_relay_surface_probes import (
        CLI_SURFACE_PROBES,
        probe_cli_surface,
        probe_surface,
    )

    command = CLI_SURFACE_PROBES.get(surface)
    if command:
        return probe_cli_surface(
            surface,
            command,
            timeout=_HOOK_SURFACE_PROBE_TIMEOUT_SECONDS,
        )
    return probe_surface(surface)


def client_executor_version(
    executor: str,
    *,
    executor_surface: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Optional[str]:
    """Return a client-observed version from env or the bounded probe cache."""
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
    if surface:
        try:
            from yoke_harness.session_relay_surface_probe_cache import (
                cached_surface_versions,
                refresh_surface_probe_cache,
            )

            cached = cached_surface_versions().get(surface)
            if cached:
                return cached
            refreshed = refresh_surface_probe_cache(
                surface,
                probe=_hook_surface_probe,
            )
            if refreshed:
                observed = refreshed[0].get("advertised_version")
                return str(observed or "").strip() or None
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
