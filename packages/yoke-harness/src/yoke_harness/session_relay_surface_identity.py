"""Per-surface identity, kept distinct from a fresh version reading.

A cache-backed version is only as good as the last time it was actually
observed. This module keeps that fact separate from two others a heartbeat
consumer must not conflate with it: whether a surface has ever been seen at
all, and whether the most recent probe actively confirmed it is gone. An
expired reading, a never-seen surface, and one confirmed removed must never
read as the same "absent" fact downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from yoke_harness.session_relay_surface_probe_cache import (
    cache_entries,
    last_good_version,
)


def cached_surface_state(
    *, state_dir: Path | None = None
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Last-known version at any age, plus surfaces confirmed absent now.

    A version survives past the shared cache's freshness window, so an
    expired reading does not read the same as a surface nobody has ever
    installed. ``confirmed_absent`` names surfaces whose most recent probe
    actively found the executable missing (``verdict == "missing"``); it
    overrides a stale version rather than mask a real removal, so a surface
    can never appear in both returned collections at once.
    """
    versions: dict[str, str] = {}
    confirmed_absent: list[str] = []
    for surface, raw in cache_entries(state_dir).items():
        if not isinstance(raw, Mapping):
            continue
        if raw.get("latest_verdict") == "missing":
            confirmed_absent.append(str(surface))
            continue
        version = last_good_version(raw)
        if version:
            versions[str(surface)] = version
    return versions, tuple(confirmed_absent)


__all__ = ["cached_surface_state"]
