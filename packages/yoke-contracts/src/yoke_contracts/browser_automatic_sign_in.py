"""Nonsecret declaration for a first-party test account's automatic sign-in."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from yoke_contracts.refusal_recovery import compose_refusal


@dataclass(frozen=True)
class AutomaticSignIn:
    url: str
    steps: tuple[dict[str, str], ...]
    credential_origins: tuple[str, ...] = ()


def parse_automatic_sign_in(raw: object, origin: str) -> AutomaticSignIn | None:
    from yoke_contracts.browser_identity import (
        BrowserIdentityError,
        validate_identity_name,
    )

    def invalid() -> None:
        raise BrowserIdentityError(
            compose_refusal(
                "browser_identity_declaration_invalid: sign_in needs mode automatic, "
                "a URL on the site's origin, and nonempty steps of {fill: SELECTOR, "
                "secret: FIELD} or {click: SELECTOR}; credential_origins must be a "
                "list of unique exact HTTPS origins without paths or userinfo",
                recovery="Correct the declaration and store values as machine-local "
                "browser-control secrets; never declare credentials in settings",
            )
        )

    if raw is None:
        return None
    if (
        not isinstance(raw, Mapping)
        or not {"mode", "url", "steps"} <= set(raw)
        or set(raw) - {"mode", "url", "steps", "credential_origins"}
    ):
        invalid()
    url = raw.get("url")
    if raw.get("mode") != "automatic" or not isinstance(url, str):
        invalid()
    try:
        target, site = urlsplit(url), urlsplit(origin)
    except ValueError:
        invalid()
    if (
        target.scheme not in {"http", "https"}
        or (target.scheme, target.netloc) != (site.scheme, site.netloc)
        or target.username is not None
        or target.password is not None
    ):
        invalid()
    credential_origins = raw.get("credential_origins", [])
    if not isinstance(credential_origins, list):
        invalid()
    seen_origins = set()
    for entry in credential_origins:
        if not isinstance(entry, str):
            invalid()
        try:
            credential = urlsplit(entry)
            port = credential.port
            if (
                credential.scheme != "https"
                or not credential.hostname
                or credential.username is not None
                or credential.password is not None
                or entry != f"https://{credential.netloc}"
                or "*" in entry
                or "\\" in entry
                or any(char.isspace() or ord(char) < 32 for char in entry)
                or credential.netloc.endswith(":")
            ):
                invalid()
        except ValueError:
            invalid()
        canonical = (credential.hostname.lower(), 443 if port is None else port)
        if canonical in seen_origins:
            invalid()
        seen_origins.add(canonical)
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
    return AutomaticSignIn(
        url=url, steps=tuple(parsed), credential_origins=tuple(credential_origins)
    )
