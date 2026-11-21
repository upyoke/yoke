"""Percent-quoted public URLs for published release artifacts."""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit


def join_public_url(base: str, *parts: str) -> str:
    value = quote_url_path(base.rstrip("/"))
    for part in parts:
        value += "/" + quote(part.strip("/"), safe="%")
    return value


def quote_url_path(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            quote(parsed.path, safe="/%"),
            parsed.query,
            parsed.fragment,
        )
    )


__all__ = ["join_public_url", "quote_url_path"]
