"""Request-scoped claim-bypass overrides for done-transition status writes.

The done transition flips ``item -> done`` and cascades ``epic-task -> done``
while BYPASSING the work-claim. Historically the bypass travelled on
process-global environment variables (``YOKE_CLAIM_BYPASS`` /
``YOKE_STATUS_SOURCE`` / ``YOKE_TASK_DONE_VERIFIED``), which are unsafe to set
in a shared server that relays many requests through one process — one
request's bypass leaks into every concurrent request's status write.

This module carries the same bypass on a per-request ContextVar instead: a
handler posts the override for the duration of ONE status write, and the
claim-verification sites read it FIRST and fall back to the environment
variables so every existing env-var caller is unchanged.

Mirrors the request-scoped "whiteboard" shape of
:func:`yoke_core.domain.project_label_policy.request_overrides` — set the token
on enter, reset it in ``finally`` — so each request (thread / async task) gets
its own isolated value and no cross-request leak.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class StatusBypassOverride:
    """The per-request claim-bypass values for a done-transition status write."""

    claim_bypass: str
    status_source: str
    task_done_verified: bool


# Request-scoped claim-bypass "whiteboard": the done-transition status handlers
# post the request's override here for the duration of the enclosed status
# write, and the verification sites read it first. The default None means no
# override is posted, so those sites fall back to the environment variables. A
# ContextVar gives each request its own isolated value, so one request's bypass
# never leaks into another's claim check.
_status_bypass: contextvars.ContextVar[Optional[StatusBypassOverride]] = (
    contextvars.ContextVar("status_claim_bypass_override", default=None)
)


@contextmanager
def status_bypass_override(
    *,
    claim_bypass: str,
    status_source: str,
    task_done_verified: bool,
) -> Iterator[None]:
    """Post the claim-bypass override on the request-scoped whiteboard."""
    token = _status_bypass.set(
        StatusBypassOverride(
            claim_bypass=claim_bypass,
            status_source=status_source,
            task_done_verified=task_done_verified,
        )
    )
    try:
        yield
    finally:
        _status_bypass.reset(token)


def resolve_claim_bypass() -> tuple[str, str]:
    """Return the request-scoped ``(claim_bypass, status_source)``.

    Returns ``("", "")`` when no override is posted, so callers fall back to
    the ``YOKE_CLAIM_BYPASS`` / ``YOKE_STATUS_SOURCE`` environment variables.
    """
    override = _status_bypass.get()
    if override is None:
        return "", ""
    return override.claim_bypass, override.status_source


def resolve_task_done_verified() -> bool:
    """Return the request-scoped epic-task done-verified flag (False if unset)."""
    override = _status_bypass.get()
    if override is None:
        return False
    return override.task_done_verified


__all__ = [
    "StatusBypassOverride",
    "status_bypass_override",
    "resolve_claim_bypass",
    "resolve_task_done_verified",
]
