"""Named browser sign-in identities a project declares for its browser profiles.

An identity is one persona: a whole Chromium profile signed into every site
that persona uses (for example a Google account, the product's own account and
a payment provider together). A project declares any number of identities
under names it chooses; Yoke attaches no meaning to a name. Each identity
lists the sites it must be signed into, and each site carries the check that
proves its session is still live, so a human is asked to sign in only for a
site whose session has really expired.

Declarations are nonsecret data in the project's ``browser-control``
capability settings::

    {"identities": {
        "member": {"sites": [
            {"site": "yoke", "origin": "https://app.example.com",
             "account": "member@example.com",
             "probe": {"url": "https://app.example.com/dashboard",
                       "signed_in_selector": "[data-test=account-menu]"}},
            {"site": "api", "origin": "https://api.example.com",
             "probe": {"url": "https://api.example.com/me",
                       "signed_in_status": 200}}
        ]}
    }}

A probe names a URL plus exactly one predicate: ``signed_in_selector`` (the
page loads, shows that element, and shows no sign-in wall) or
``signed_in_status`` (the URL, requested with the profile's cookies and
without following redirects, answers that HTTP status).

The ``default`` identity always exists. It is the project's original single
profile, so a project that declares nothing keeps working unchanged; a
project may also declare sites for ``default``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

DEFAULT_IDENTITY = "default"
#: Home-relative directory where a Test Machine keeps its live identity
#: profiles. It sits outside ``~/.yoke`` so a full reset keeps it, the same way
#: the reset keeps live harness logins, while ``~/.yoke`` stays absent. A
#: restored copy of a session is the cookies the site has since rotated, so
#: identities are kept live and never sealed into a baseline. Its presence is
#: what marks a machine as keeping live identities: the product links each
#: identity's profile path into it (see ``yoke_cli.config.browser_profile``).
LIVE_IDENTITY_STORE_HOME_ENTRY = ".yoke-browser-identities"
IDENTITIES_SETTING = "identities"
IDENTITY_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_SITE_KEYS = frozenset({"site", "origin", "account", "probe"})
_PROBE_PREDICATES = ("signed_in_selector", "signed_in_status")
_DECLARE_RECOVERY = (
    "Declare it in the project's browser-control capability settings, for "
    "example `yoke projects capability-settings merge --project P "
    "--cap-type browser-control --set identities.NAME.sites=[...]`."
)


class BrowserIdentityError(ValueError):
    """A declaration or identity reference that cannot be used, with recovery."""


@dataclass(frozen=True)
class SignInCheck:
    """One site an identity must be signed into, and how to prove it is."""

    site: str
    origin: str
    probe_url: str
    signed_in_selector: str | None = None
    signed_in_status: int | None = None
    account: str = ""

    def as_probe(self) -> dict[str, object]:
        """The JSON the browser runtime's sign-in check consumes."""
        probe: dict[str, object] = {"site": self.site, "url": self.probe_url}
        if self.signed_in_selector is not None:
            probe["signed_in_selector"] = self.signed_in_selector
        if self.signed_in_status is not None:
            probe["signed_in_status"] = self.signed_in_status
        return probe


@dataclass(frozen=True)
class BrowserIdentity:
    name: str
    sites: tuple[SignInCheck, ...] = ()


def live_identity_store_relative_path(project: str, identity: str) -> PurePosixPath:
    """Home-relative store directory holding one project identity's live profile."""
    return (
        PurePosixPath(LIVE_IDENTITY_STORE_HOME_ENTRY)
        / project
        / validate_identity_name(identity)
    )


def validate_identity_name(name: object) -> str:
    """Return a usable identity name or raise naming the accepted shape."""
    value = str(name or "").strip()
    if not IDENTITY_NAME_PATTERN.fullmatch(value):
        raise BrowserIdentityError(
            f"browser_identity_name_invalid: {value!r} is not an identity name. "
            "Use 1-40 lowercase letters, digits or hyphens, starting and "
            "ending with a letter or digit."
        )
    return value


def _web_url(value: object, label: str) -> str:
    text = str(value or "").strip()
    parts = urlsplit(text)
    if parts.scheme not in {"https", "http"} or not parts.netloc:
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {label} must be an absolute "
            f"http(s) URL, got {text!r}."
        )
    return text


def _sign_in_check(identity: str, index: int, raw: object) -> SignInCheck:
    where = f"identities.{identity}.sites[{index}]"
    if not isinstance(raw, Mapping):
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where} must be an object."
        )
    unknown = sorted(set(raw) - _SITE_KEYS)
    if unknown:
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where} has unknown keys "
            f"{unknown}; allowed: {sorted(_SITE_KEYS)}."
        )
    site = validate_identity_name(raw.get("site"))
    probe = raw.get("probe")
    if not isinstance(probe, Mapping):
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where}.probe must be an "
            "object with url and one of signed_in_selector or signed_in_status."
        )
    unknown = sorted(set(probe) - {"url", *_PROBE_PREDICATES})
    predicates = [key for key in _PROBE_PREDICATES if key in probe]
    if unknown or len(predicates) != 1:
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where}.probe needs url and "
            "exactly one of signed_in_selector or signed_in_status."
        )
    selector = probe.get("signed_in_selector")
    status = probe.get("signed_in_status")
    if selector is not None and not (isinstance(selector, str) and selector.strip()):
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where}.probe."
            "signed_in_selector must be a non-empty selector."
        )
    if status is not None and not (
        isinstance(status, int)
        and not isinstance(status, bool)
        and 100 <= status <= 599
    ):
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where}.probe."
            "signed_in_status must be an HTTP status code."
        )
    account = raw.get("account", "")
    if not isinstance(account, str):
        raise BrowserIdentityError(
            f"browser_identity_declaration_invalid: {where}.account must be text."
        )
    return SignInCheck(
        site=site,
        origin=_web_url(raw.get("origin"), f"{where}.origin"),
        probe_url=_web_url(probe.get("url"), f"{where}.probe.url"),
        signed_in_selector=selector.strip() if selector is not None else None,
        signed_in_status=status,
        account=account.strip(),
    )


def parse_identity_declarations(
    settings: Mapping[str, object] | None,
) -> dict[str, BrowserIdentity]:
    """Parse browser-control settings into identities; ``default`` always exists."""
    raw = (settings or {}).get(IDENTITIES_SETTING) or {}
    if not isinstance(raw, Mapping):
        raise BrowserIdentityError(
            "browser_identity_declaration_invalid: identities must be an object "
            "keyed by identity name."
        )
    identities = {DEFAULT_IDENTITY: BrowserIdentity(DEFAULT_IDENTITY)}
    for name, body in raw.items():
        identity = validate_identity_name(name)
        if not isinstance(body, Mapping) or set(body) - {"sites"}:
            raise BrowserIdentityError(
                f"browser_identity_declaration_invalid: identities.{identity} "
                "must be an object whose only key is sites."
            )
        sites = body.get("sites") or []
        if not isinstance(sites, list):
            raise BrowserIdentityError(
                f"browser_identity_declaration_invalid: identities.{identity}"
                ".sites must be a list."
            )
        checks = tuple(
            _sign_in_check(identity, index, site) for index, site in enumerate(sites)
        )
        names = [check.site for check in checks]
        if len(set(names)) != len(names):
            raise BrowserIdentityError(
                f"browser_identity_declaration_invalid: identities.{identity} "
                "names a site twice; a profile holds one login per site, so a "
                "second account on the same site is a second identity."
            )
        identities[identity] = BrowserIdentity(identity, checks)
    return identities


def case_browser_identity(method_config: Mapping[str, object] | None) -> str:
    """The identity a Browser case runs as: ``browser_identity`` or ``default``."""
    raw = (method_config or {}).get("browser_identity")
    return DEFAULT_IDENTITY if raw is None else validate_identity_name(raw)


def mission_browser_identities(config: Mapping[str, object] | None) -> list[str]:
    """The identities an exploratory mission needs signed in before it browses."""
    raw = (config or {}).get("browser_identities", [])
    if not isinstance(raw, list):
        raise BrowserIdentityError(
            "browser_identities_invalid: method_config.browser_identities must "
            "be a list of identity names."
        )
    names = [validate_identity_name(name) for name in raw]
    if len(set(names)) != len(names):
        raise BrowserIdentityError(
            "browser_identities_invalid: method_config.browser_identities names "
            "an identity twice."
        )
    return names


def select_identity(
    identities: Mapping[str, BrowserIdentity], name: str | None
) -> BrowserIdentity:
    """Return the named identity (``default`` when omitted) or refuse by name."""
    selected = validate_identity_name(name or DEFAULT_IDENTITY)
    if selected in identities:
        return identities[selected]
    raise BrowserIdentityError(
        f"browser_identity_undeclared: this project declares no browser identity "
        f"{selected!r}; declared: {', '.join(sorted(identities))}. " + _DECLARE_RECOVERY
    )


__all__ = [
    "DEFAULT_IDENTITY",
    "IDENTITIES_SETTING",
    "LIVE_IDENTITY_STORE_HOME_ENTRY",
    "BrowserIdentity",
    "BrowserIdentityError",
    "SignInCheck",
    "case_browser_identity",
    "live_identity_store_relative_path",
    "mission_browser_identities",
    "parse_identity_declarations",
    "select_identity",
    "validate_identity_name",
]
