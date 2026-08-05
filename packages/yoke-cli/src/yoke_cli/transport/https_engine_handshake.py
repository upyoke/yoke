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
    if not local_version:
        # A source checkout has no distribution version, which used to end
        # the comparison here. That silenced it in the one environment where
        # drift is continuous rather than occasional — a checkout moves per
        # commit while a release moves per tag. Ask the axis that moves.
        _warn_on_source_checkout_skew(raw_server_version, sensitive_values)
        return
    if local_version == raw_server_version:
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


def _warn_on_source_checkout_skew(
    raw_server_version: str, sensitive_values: tuple[str, ...] = ()
) -> None:
    """Compare a source checkout's HEAD against the server's release commit.

    The server advertises a version rather than a commit, but a release
    version names an annotated tag, and a checkout carrying that tag can
    resolve it to the commit itself. So no protocol change is needed to
    reach the axis that actually moves here.

    Stays advisory in every direction, including when nothing can be
    resolved: this is a hint about why behavior might differ, never a gate.
    """
    global _skew_warned
    from pathlib import Path

    from yoke_cli.transport import source_build_skew

    comparison = source_build_skew.compare_to_server_build(
        str(Path.cwd()), f"v{raw_server_version}"
    )
    if not comparison.differs:
        return
    _skew_warned = True
    detail = redact_text(source_build_skew.describe(comparison), sensitive_values)
    print(f"yoke: {detail[:300]}", file=sys.stderr)


__all__ = [
    "ENGINE_VERSION_HEADER",
    "ServerHandshake",
    "observe_server_version",
]
