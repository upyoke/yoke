"""Open a self-host workbench using the active connection's credential."""

from typing import Any

from yoke_cli.commands.universe_ui_connection import UniverseUiError
from yoke_cli.config.self_host_browser_sign_in import (
    mint_self_host_sign_in_link,
    self_host_connection,
    self_host_sign_in_method,
    self_host_url,
)


def self_host_report(*, host: str | None, port: int | None) -> dict[str, Any] | None:
    """Return a private browser door for self-host; other modes keep their path."""
    connection = self_host_connection()
    if connection is None:
        return None
    if host is not None or port is not None:
        raise UniverseUiError(
            "self_host_ui_local_flags: --host and --port configure a local daemon; "
            "run `yoke ui up` without them to open this server"
        )
    recovery = "run `yoke ui up` again"
    origin = self_host_url(connection)
    method = self_host_sign_in_method(connection, recovery=recovery)
    private_url = origin + "/"
    if method == "token":
        link = mint_self_host_sign_in_link(connection, recovery=recovery)
        if link is None:
            method = "oidc"
        else:
            private_url = link
    return {
        "mode": "self-host",
        "env": connection.get("env"),
        "auth_method": method,
        "url": origin,
        "private_url": private_url,
    }
