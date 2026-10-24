"""Foundational typed records the shared hook runner passes between policies.

`HookContext` is the typed input every chain-eligible policy receives.
`HookDecision` is the typed output every policy returns. `Outcome` and `Next`
enumerate the closed decision vocabulary shared by the runner and policies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import Any

from yoke_contracts.hook_runner.command_extract import extract_command
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell


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

    The context is intentionally minimal. Anything else a policy needs is read
    on demand via `yoke_core.hooks.helpers_*` or `yoke_core.domain.*`.
    `shell` is the one shared parse of the Bash command, built on first use
    and reused by every later policy in the chain.
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

    @cached_property
    def shell(self) -> ShellParse:
        return parse_shell(extract_command(self.payload))


@dataclass(frozen=True)
class HookDecision:
    """Typed output every policy returns.

    Denials carry a plain reason in `message` and their registered check id in
    `audit_fields["check_id"]`; only decision_render builds harness envelopes.
    `outcome` carries the closed `Outcome` value. `block` preserves Claude's
    blocking-vs-non-blocking semantics (orthogonal to outcome to keep the
    renderer side clean). `next` controls chain advancement.
    """

    outcome: Outcome
    message: str = ""
    audit_fields: dict[str, Any] = field(default_factory=dict)
    block: bool = False
    next: Next = Next.CONTINUE
