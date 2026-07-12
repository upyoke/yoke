"""Redirect-free network opening for credential-bearing HTTPS relays."""

from __future__ import annotations

from typing import Any
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    """Keep actor credentials on the configured function endpoint."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


_OPENER = build_opener(NoRedirect())


def open_no_redirect(request: Request, *, timeout: float):
    """Open one request while surfacing every 3xx as an HTTP error."""

    return _OPENER.open(request, timeout=timeout)


__all__ = ["NoRedirect", "open_no_redirect"]
