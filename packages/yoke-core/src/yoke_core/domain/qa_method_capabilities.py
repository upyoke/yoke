"""Canonical capability-set handling for registered QA methods."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


class QaMethodCapabilityError(ValueError):
    """A stored or authored QA method capability set is invalid."""


def capability_kinds(value: Any, *, subject: str = "QA method") -> tuple[str, ...]:
    """Return one sorted, duplicate-free capability set.

    Database values are JSON arrays. Python callers may supply any finite
    iterable of strings. Invalid stored values fail closed instead of turning
    a case with unknown prerequisites into an apparently runnable one.
    """
    decoded = value
    if value is None:
        decoded = []
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError as exc:
            raise QaMethodCapabilityError(
                f"{subject} required capability kinds must be a JSON array"
            ) from exc
    if isinstance(decoded, (str, bytes, dict)) or not isinstance(decoded, Iterable):
        raise QaMethodCapabilityError(
            f"{subject} required capability kinds must be an array"
        )
    kinds: list[str] = []
    for raw in decoded:
        if not isinstance(raw, str) or not raw.strip():
            raise QaMethodCapabilityError(
                f"{subject} required capability kinds must be non-empty strings"
            )
        kinds.append(raw.strip())
    return tuple(sorted(set(kinds)))


# What each registered runner provisions on the machine that executes its
# cases, before it uses it. This is a runner property, never a property of
# the capability kind: a kind is exempt from admission only for a runner that
# actually installs and probes it where the case runs.
#
# ``browser_substrate`` starts the machine-local browser daemon, which
# materializes the runtime, resolves or installs Node, runs ``npm install``,
# probes Chromium and installs it when absent, and fails with a named reason
# and recovery when it cannot. ``agent_mission`` walks a registered Test
# Machine, and its dispatch contract requires the walker to run ``yoke qa
# browser setup`` on that target host before any browser step — a remote
# execution host, but still the one the case runs on. Nothing here is a
# preparation gate the platform runs for either runner: the declaration says
# who supplies the capability where the case executes, and each runner's own
# path is what supplies it.
#
# Every other runner provisions nothing, so every capability kind it declares
# stays a gate admission enforces: a Command case declaring ``browser-control``
# is refused exactly as before, because nothing on its path would install a
# browser. Kinds naming project or host authority rather than installable
# tooling — ``test-machine``, ``desktop-control`` — are never listed here, so
# an agent mission still cannot run until its project registers a Test Machine.
RUNNER_HOST_PROVISIONED_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {
    "browser_substrate": ("browser-control",),
    "agent_mission": ("browser-control",),
}


def host_provisioned_capability_kinds(
    runner_id: Any,
    value: Any,
    *,
    subject: str = "QA case",
) -> tuple[str, ...]:
    """Return the kinds in ``value`` that ``runner_id`` provisions where it runs."""
    provisioned = set(
        RUNNER_HOST_PROVISIONED_CAPABILITY_KINDS.get(str(runner_id or ""), ())
    )
    return tuple(
        kind
        for kind in capability_kinds(value, subject=subject)
        if kind in provisioned
    )


def encoded_capability_kinds(
    value: Any,
    *,
    subject: str = "QA method",
) -> str:
    """Encode a capability set in its portable database representation."""
    return json.dumps(list(capability_kinds(value, subject=subject)))


def missing_capability_kinds(
    required: Any,
    available: Any,
    *,
    subject: str = "QA case",
) -> tuple[str, ...]:
    """Return every declared prerequisite absent from the execution host."""
    required_set = set(capability_kinds(required, subject=subject))
    available_set = set(capability_kinds(available, subject="execution host"))
    return tuple(sorted(required_set - available_set))


__all__ = [
    "RUNNER_HOST_PROVISIONED_CAPABILITY_KINDS",
    "QaMethodCapabilityError",
    "capability_kinds",
    "encoded_capability_kinds",
    "host_provisioned_capability_kinds",
    "missing_capability_kinds",
]
