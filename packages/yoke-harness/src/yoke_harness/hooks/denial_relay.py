"""Best-effort relay of a client-local denial's audit fields to the server.

``evaluate_local_subset``'s ``LOCAL_STATE_POLICIES`` deny without ever
calling ``/hooks/evaluate`` (the relay client returns immediately, skipping
the round-trip its verdict doesn't need), so a client-local denial has no
other way to leave a durable ``HarnessToolCallDenied`` row. This module
stays free of any ``yoke_core`` import — the client/server package boundary
forbids it — and reuses the same bounded-HTTP transport ``relay.py`` already
depends on.
"""

from __future__ import annotations

import json
import urllib.request

from yoke_cli.transport.bounded_json_http import request_json
from yoke_cli.transport.https import HttpsConnection

DENIAL_AUDIT_PATH = "/v1/hooks/denial-audit"


def relay_denial_audit(connection: HttpsConnection, audit: dict) -> None:
    """POST *audit* fire-and-forget. Never raises; never blocks the hook."""
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
            timeout_seconds=3.0,
            replay_safe=False,
            allow_loopback_http=True,
            response_limit_bytes=4096,
            sensitive_values=(connection.token,),
            opener=urllib.request.urlopen,
        )
    except Exception:
        pass


__all__ = ["DENIAL_AUDIT_PATH", "relay_denial_audit"]
