"""Who may talk to a loopback universe view: the per-run session token.

The view server binds ``127.0.0.1`` only, but loopback is shared with
every other process on the machine, so admission still needs a secret.
One random token per run is it. The token arrives as ``?token=`` on the
first hit and is exchanged for an HttpOnly cookie, so the tokened URL
drops out of browser history and later asset and API requests ride the
cookie.

Kept apart from :mod:`yoke_core.ui.server` because admission is its own
concern: the server decides what to serve, this decides who is admitted.
"""

from __future__ import annotations

import secrets

#: ``secrets.token_urlsafe`` byte length for the per-run session token.
SESSION_TOKEN_BYTES = 32

#: Prefix of the cookie the app-shell response sets. The bind port
#: completes the name — see :func:`session_cookie_name`.
SESSION_COOKIE_PREFIX = "yoke_ui_session_"


def mint_session_token() -> str:
    """A fresh admission secret for one run of the view server."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def session_cookie_name(port: int) -> str:
    """Name the session cookie after the port that issued it.

    Cookies are scoped by host and path but never by port, so every
    loopback view on ``127.0.0.1`` would otherwise share one cookie: a
    second view's redirect overwrites the first one's token, and each
    server then answers the other's browser with 401. Two views is the
    ordinary case — the machine daemon serving the universe you work in
    while a disposable one serves the universe you are rendering for
    evidence — so the port belongs in the name.
    """
    return f"{SESSION_COOKIE_PREFIX}{int(port)}"


def token_matches(candidate: str, token: str) -> bool:
    """Constant-time token comparison.

    Byte-wise on purpose: ``secrets.compare_digest`` raises ``TypeError``
    on non-ASCII ``str`` input, and a hostile/garbled candidate must land
    on the clean 401 path, never a 500.
    """
    return secrets.compare_digest(
        candidate.encode("utf-8"),
        token.encode("utf-8"),
    )


__all__ = [
    "SESSION_COOKIE_PREFIX",
    "SESSION_TOKEN_BYTES",
    "mint_session_token",
    "session_cookie_name",
    "token_matches",
]
