"""Server engine-version handshake carried on HTTPS relay responses.

The server advertises the engine version it runs as a response header.
The handshake records it — and, for a source checkout, the git comparison
against that build — so the refusals where skew explains the failure can
name it: the version-skew gate, a payload-contract refusal
(:func:`yoke_cli.transport.control_plane_payload.required_field`), and the
relay build-compatibility refusal
(:mod:`yoke_harness.session_relay_build_compatibility`).

It prints nothing itself. A warning on every relay response said the same
thing hundreds of times a session, which is how a real signal becomes
scenery; skew belongs where it explains a failure, not ahead of output that
succeeded. Operator-facing drift reporting is a separate comparison —
:mod:`yoke_cli.operating_layer_drift` — and never depended on this banner.

The handshake never blocks a relay. An absent header (older server, or
one running from a source tree), an unresolvable local version, or
matching versions all leave the relay exactly as it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from yoke_cli.transport import control_plane_payload, source_build_skew
from yoke_contracts.engine_version import (
    ENGINE_VERSION_HEADER,
    local_handshake_version,
)


@dataclass
class ServerHandshake:
    """Per-relay record of what the server advertised about itself.

    Passed in by callers that need the handshake value for this exact
    response: the version-skew gate names the server's engine version in
    its error.
    """

    engine_version: str = ""


def observe_server_version(
    headers,
    handshake: Optional[ServerHandshake],
) -> None:
    """Record the advertised engine version and this checkout's skew from it.

    A source checkout has no distribution version, so comparing versions
    would disable itself in the one environment where drift is continuous
    rather than occasional — a checkout moves per commit while a release
    moves per tag. Ask the axis that moves, and record the answer for the
    refusals and reports that use it.
    """
    raw_server_version = _header_engine_version(headers)
    if handshake is not None:
        handshake.engine_version = raw_server_version
    local_version = local_handshake_version() if raw_server_version else ""
    source_comparison = (
        _source_checkout_comparison(raw_server_version)
        if raw_server_version and not local_version
        else None
    )
    server_build = f"v{raw_server_version}" if raw_server_version else ""
    control_plane_payload.observe_server_build(server_build, source_comparison)


def _header_engine_version(headers) -> str:
    """The server's advertised engine version, ``""`` when unavailable."""
    if headers is None:
        return ""
    get = getattr(headers, "get", None)
    if not callable(get):
        return ""
    return str(get(ENGINE_VERSION_HEADER) or "")


def _loaded_source_checkout() -> Optional[str]:
    """Git checkout that owns the imported ``yoke_cli`` package, if any.

    Caller cwd is the wrong tree: a source-linked CLI invoked from another
    project still loads ``yoke_cli`` from this checkout, and git history
    of the caller project is not Yoke client/server skew.
    """
    return _loaded_source_checkout_cached()


@lru_cache(maxsize=1)
def _loaded_source_checkout_cached() -> Optional[str]:
    import yoke_cli
    from yoke_contracts.install_binding import source_checkout_root

    root = source_checkout_root(yoke_cli.__file__)
    return str(root) if root is not None else None


def _source_checkout_comparison(
    raw_server_version: str,
) -> Optional[source_build_skew.BuildComparison]:
    """This checkout's git distance from the server build, for skew readers."""
    checkout = _loaded_source_checkout()
    if checkout is None:
        return None
    return source_build_skew.compare_to_server_build(checkout, f"v{raw_server_version}")


__all__ = [
    "ENGINE_VERSION_HEADER",
    "ServerHandshake",
    "observe_server_version",
]
