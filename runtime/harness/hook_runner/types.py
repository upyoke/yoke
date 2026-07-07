"""Foundational typed records the shared hook runner passes between policies.

`HookContext` is the typed input every chain-eligible policy receives.
`HookDecision` is the typed output every policy returns. `Outcome` and `Next`
enumerate the closed value sets named in the epic spec's Target Architecture
section so the runner and policies share one vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    """Closed set of decision outcomes a policy may emit."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    SUPPRESSION_ATTEMPTED = "suppression_attempted"
    AUDIT_ONLY = "audit_only"
    NOOP = "noop"


class Next(str, Enum):
    """Whether the runner advances to the next policy or stops the chain."""

    CONTINUE = "continue"
    STOP = "stop"


@dataclass(frozen=True)
class HookContext:
    """Typed input every policy receives.

    Field shape mirrors the epic spec's Target Architecture section. The
    context is intentionally minimal — anything else a policy needs is read
    on-demand via `runtime.harness.hook_helpers_*` or `yoke_core.domain.*`.
    """

    event_name: str
    executor_family: str
    executor_surface: str
    payload: dict[str, Any]
    tool_name: str | None = None
    command_body: str | None = None
    cwd: str | None = None
    target_root: str | None = None
    session_id: str | None = None
    item_id: int | None = None
    now: datetime | None = None
    # True when the evaluation runs server-side on behalf of a remote client
    # (``/v1/hooks/evaluate``): client-local filesystem/git/env state is NOT
    # available, and ``cwd`` is payload-borne only (no ``os.getcwd`` fallback).
    remote: bool = False


@dataclass(frozen=True)
class HookDecision:
    """Typed output every policy returns.

    `outcome` carries the closed `Outcome` value. `block` preserves Claude's
    blocking-vs-non-blocking semantics (orthogonal to outcome to keep the
    renderer side clean). `next` controls chain advancement.
    """

    outcome: Outcome
    message: str = ""
    audit_fields: dict[str, Any] = field(default_factory=dict)
    block: bool = False
    next: Next = Next.CONTINUE
