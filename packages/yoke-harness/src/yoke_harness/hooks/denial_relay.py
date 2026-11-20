"""Relay of a client-local denial's audit fields to the server.

``evaluate_local_subset``'s client-home policies deny without ever
calling ``/hooks/evaluate`` (the relay client returns immediately, skipping
the round-trip its verdict doesn't need), so a client-local denial has no
other way to leave a durable ``HarnessToolCallDenied`` row. This module
stays free of any ``yoke_core`` import — the client/server package boundary
forbids it — and reuses the same bounded-HTTP transport ``relay.py`` already
depends on.

The audit never delays the deny it describes. A resident evaluator holds
the audit until it has sent the hook's reply; a one-shot hook process posts
it only inside what is left of its own hook budget.
"""

from __future__ import annotations

import json
import urllib.request
from contextvars import ContextVar, Token
from typing import Callable

from yoke_contracts.bounded_json_http import request_json
from yoke_cli.transport.https import HttpsConnection
from yoke_harness.hooks.deadline import HookDeadline

DENIAL_AUDIT_PATH = "/v1/hooks/denial-audit"
AUDIT_TIMEOUT_MS = 3000

_HELD: ContextVar[list[Callable[[], None]] | None] = ContextVar(
    "yoke_held_denial_audits", default=None
)


def relay_denial_audit(
    connection: HttpsConnection,
    audit: dict,
    *,
    timeout_seconds: float = AUDIT_TIMEOUT_MS / 1000,
) -> None:
    """POST *audit*; transport failures never raise."""
    if not audit:
        return
    url = connection.api_url.rstrip("/") + DENIAL_AUDIT_PATH
    http_request = urllib.request.Request(
        url,
        data=json.dumps(audit).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {connection.token}",
        },
    )
    try:
        request_json(
            http_request,
            timeout_seconds=timeout_seconds,
            replay_safe=False,
            allow_private_http=True,
            response_limit_bytes=4096,
            sensitive_values=(connection.token,),
            opener=urllib.request.urlopen,
        )
    except Exception:
        pass


def submit_denial_audit(
    connection: HttpsConnection, audit: dict, deadline: HookDeadline
) -> None:
    """Record a denial without spending the time its deny reply needs."""
    if not audit:
        return
    held = _HELD.get()
    if held is not None:
        held.append(lambda: relay_denial_audit(connection, audit))
        return
    if deadline.expired():
        return
    relay_denial_audit(
        connection,
        audit,
        timeout_seconds=deadline.child_timeout_ms(AUDIT_TIMEOUT_MS) / 1000,
    )


def hold_denial_audits() -> Token:
    """Hold this thread's denial audits until ``send_held_denial_audits``."""
    return _HELD.set([])


def send_held_denial_audits(token: Token) -> None:
    """Post the audits held since ``token``, after the reply has been sent."""
    held = _HELD.get() or []
    _HELD.reset(token)
    for post in held:
        post()


__all__ = [
    "AUDIT_TIMEOUT_MS",
    "DENIAL_AUDIT_PATH",
    "hold_denial_audits",
    "relay_denial_audit",
    "send_held_denial_audits",
    "submit_denial_audit",
]
