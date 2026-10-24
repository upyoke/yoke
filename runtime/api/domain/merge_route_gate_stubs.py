"""Admit the landing route's own gates for merge tests that stub the route.

``yoke merge item`` asks the route gates (integration dependencies,
candidate review, merge-queue probe, verification command) during landing
readiness. A test that replaces the whole landing route admits them here.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import merge_landing_readiness as readiness_gate
from yoke_core.domain.merge_queue_route_selection import RouteAdmission


def admit_route_gates(
    monkeypatch: Any,
    *,
    admission: RouteAdmission = RouteAdmission(),
    verification: tuple[str, str, list] = ("full", "make test", []),
) -> None:
    monkeypatch.setattr(readiness_gate, "route_admission", lambda **_k: admission)
    monkeypatch.setattr(
        readiness_gate, "resolve_verification", lambda *_a, **_k: verification
    )
