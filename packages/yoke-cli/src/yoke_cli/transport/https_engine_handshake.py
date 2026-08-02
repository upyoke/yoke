"""Server engine-version handshake carried on HTTPS relay responses.

The server advertises the engine version it runs as a response header.
Two consumers read it: the once-per-process advisory warning that the
two sides have skewed, and the version-skew gate, which needs the value
observed on one specific response so its typed error can name it.

The handshake never blocks a relay. An absent header (older server, or
one running from a source tree), an unresolvable local version, or
matching versions all leave the relay exactly as it was.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from yoke_cli.transport.https_response_policy import redact_text
from yoke_contracts.engine_version import (
    ENGINE_VERSION_HEADER,
    local_handshake_version,
)

# Process-wide latch: the engine-version skew warning prints at most once.
_skew_warned = False


@dataclass
class ServerHandshake:
    """Per-relay record of what the server advertised about itself.

    Passed in by callers that need the handshake value for this exact
    response — the version-skew gate names the server's engine version
    in its error — rather than for the process-wide advisory warning.
    """

    engine_version: str = ""


def observe_server_version(
    headers,
    sensitive_values: tuple[str, ...],
    handshake: Optional[ServerHandshake],
) -> None:
    """Record the advertised engine version, then warn once on skew."""
    raw_server_version = _header_engine_version(headers)
    if handshake is not None:
        handshake.engine_version = raw_server_version
    _warn_on_engine_version_skew(raw_server_version, sensitive_values)


def _header_engine_version(headers) -> str:
    """The server's advertised engine version, ``""`` when unavailable."""
    if headers is None:
        return ""
    get = getattr(headers, "get", None)
    if not callable(get):
        return ""
    return str(get(ENGINE_VERSION_HEADER) or "")


def _warn_on_engine_version_skew(
    raw_server_version: str, sensitive_values: tuple[str, ...] = ()
) -> None:
    """Print one stderr warning per process when server/client versions skew."""
    global _skew_warned
    if _skew_warned or not raw_server_version:
        return
    local_version = local_handshake_version()
    if not local_version or local_version == raw_server_version:
        return
    _skew_warned = True
    server_version = redact_text(raw_server_version, sensitive_values)[:128]
    displayed_local_version = redact_text(local_version, sensitive_values)[:128]
    print(
        f"yoke: server engine version {server_version} differs from the "
        f"local install {displayed_local_version}; commands still relay — update "
        "the older side if behavior looks off",
        file=sys.stderr,
    )


__all__ = [
    "ENGINE_VERSION_HEADER",
    "ServerHandshake",
    "observe_server_version",
]
