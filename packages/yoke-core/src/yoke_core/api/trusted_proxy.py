"""Self-host forwarding with the socket peer's trust preserved for origin checks."""

from __future__ import annotations

import argparse
import ipaddress
import os

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

TRUSTED_PROXIES_ENV = "YOKE_API_TRUSTED_PROXIES"
DEFAULT_TRUSTED_PROXIES = "127.0.0.1"


def parse_trusted_proxies(value: str) -> str:
    """Accept only explicit IPs/networks, or an empty list that trusts none."""
    entries = [entry.strip() for entry in value.split(",")] if value.strip() else []
    for entry in entries:
        try:
            if "/" in entry:
                ipaddress.ip_network(entry)
            else:
                ipaddress.ip_address(entry)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"trusted_proxies_invalid: {entry!r} is not an IP address or CIDR. "
                f"Set {TRUSTED_PROXIES_ENV} (or --trusted-proxies) to "
                "comma-separated proxy IPs/CIDRs, or empty to trust none; '*' "
                "is forbidden. In the bundle, edit .env and restart with "
                "yoke self-host init --dir PATH --protect-existing --start."
            ) from exc
    return ",".join(entries)


class TrustedProxyHeadersMiddleware(ProxyHeadersMiddleware):
    """Apply the external host using Uvicorn's original transport-peer matcher."""

    def __init__(self, app, trusted_hosts: str):
        super().__init__(app, trusted_hosts=parse_trusted_proxies(trusted_hosts))

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            peer = scope.get("client")
            if peer and peer[0] in self.trusted_hosts:
                forwarded_host = dict(scope["headers"]).get(b"x-forwarded-host")
                if forwarded_host:
                    # Normalize once so origin checks and URL consumers agree.
                    headers = [
                        (name, value)
                        for name, value in scope["headers"]
                        if name != b"host"
                    ]
                    scope = {**scope, "headers": [*headers, (b"host", forwarded_host)]}
        await super().__call__(scope, receive, send)


def create_app():
    """Worker factory: wrap the selected ASGI app before any headers are applied."""
    from uvicorn import Config
    from yoke_core.api.server_entrypoint import APP_ENV, DEFAULT_APP

    config = Config(
        os.environ.get(APP_ENV, DEFAULT_APP), proxy_headers=False, log_config=None
    )
    config.load()
    return TrustedProxyHeadersMiddleware(
        config.loaded_app, os.environ.get(TRUSTED_PROXIES_ENV, DEFAULT_TRUSTED_PROXIES)
    )


def run_self_host(settings, **kwargs):
    """Pass flag overrides to spawned workers through their inherited environment."""
    import uvicorn
    from yoke_core.api.server_entrypoint import APP_ENV

    overrides = {
        APP_ENV: settings.app,
        TRUSTED_PROXIES_ENV: settings.trusted_proxies,
    }
    prior = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        uvicorn.run(
            "yoke_core.api.trusted_proxy:create_app",
            factory=True,
            proxy_headers=False,  # The factory applies forwarding once, at the peer.
            **kwargs,
        )
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
