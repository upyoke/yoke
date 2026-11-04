"""Nonsecret declaration for a first-party test account's automatic sign-in."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AutomaticSignIn:
    url: str
    steps: tuple[dict[str, str], ...]


def parse_automatic_sign_in(raw: object, origin: str) -> AutomaticSignIn | None:
    from yoke_contracts.browser_identity import (
        BrowserIdentityError,
        validate_identity_name,
    )

    def invalid() -> None:
        raise BrowserIdentityError(
            "browser_identity_declaration_invalid: sign_in needs mode automatic, "
            "a URL on the site's origin, and nonempty steps of {fill: SELECTOR, "
            "secret: FIELD} or {click: SELECTOR}. Store values as machine-local "
            "browser-control secrets; never declare credentials in settings."
        )

    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"mode", "url", "steps"}:
        invalid()
    url = raw.get("url")
    if raw.get("mode") != "automatic" or not isinstance(url, str):
        invalid()
    target, site = urlsplit(url), urlsplit(origin)
    if (
        target.scheme not in {"http", "https"}
        or (target.scheme, target.netloc) != (site.scheme, site.netloc)
        or target.username is not None
        or target.password is not None
    ):
        invalid()
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        invalid()
    parsed = []
    for step in steps:
        if not isinstance(step, Mapping):
            invalid()
        if set(step) == {"fill", "secret"}:
            if validate_identity_name(step["secret"]) != step["secret"]:
                invalid()
            selector = step["fill"]
        elif set(step) == {"click"}:
            selector = step["click"]
        else:
            invalid()
        if not isinstance(selector, str) or not selector.strip():
            invalid()
        parsed.append(dict(step))
    return AutomaticSignIn(url=url, steps=tuple(parsed))
