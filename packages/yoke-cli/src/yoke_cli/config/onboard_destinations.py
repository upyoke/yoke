"""Deployment-destination vocabulary for ``yoke onboard``.

One shared Yoke engine, three deployment destinations: the machine's own
embedded local universe, a self-hosted team server, or the hosted platform
at upyoke.com. The destination an onboarding run picks changes only the
sign-in step — local replaces sign-in with the local-universe bootstrap,
server connects to a pasted URL, hosted connects to the platform endpoints
— and is stored as a non-secret input so resumed runs restore it.

Dependency-light on purpose: the non-interactive CLI lane resolves the
destination without importing any Textual-backed wizard module.
"""

from __future__ import annotations

from yoke_contracts.api_urls import HOSTED_PROD_URL, HOSTED_STAGE_URL

DESTINATION_LOCAL = "local"
DESTINATION_SERVER = "server"
DESTINATION_HOSTED = "hosted"
DESTINATIONS = (DESTINATION_LOCAL, DESTINATION_SERVER, DESTINATION_HOSTED)

#: The public-launch picker starts with the private, no-signup path. Hosted
#: and team-server destinations remain one explicit selection away.
DEFAULT_DESTINATION = DESTINATION_LOCAL

#: Environment override giving non-interactive parity with the picker:
#: ``local`` / ``hosted`` name destinations directly; an http(s) URL means
#: a team server at that URL.
DESTINATION_OVERRIDE = "YOKE_ONBOARD_DESTINATION"

#: Hosted-platform environment ids — the row values of the hosted lane's
#: environment select, doubling as the machine-config env labels the
#: hosted sign-in writes.
ENV_PRODUCTION = "prod"
ENV_STAGE = "stage"

#: Machine-config env label the sign-in destinations default to when no
#: explicit ``--env`` was given (the hosted production id; a team server
#: keeps the same default label unless overridden).
DEFAULT_SIGN_IN_ENV = ENV_PRODUCTION

_HOSTED_URLS = frozenset(
    url.rstrip("/") for url in (HOSTED_PROD_URL, HOSTED_STAGE_URL)
)


def is_hosted_url(api_url: object) -> bool:
    """Whether ``api_url`` is one of the hosted-platform endpoints."""
    return str(api_url or "").strip().rstrip("/") in _HOSTED_URLS


def destination_for_api_url(api_url: object) -> str:
    """The destination an explicit API URL implies."""
    return DESTINATION_HOSTED if is_hosted_url(api_url) else DESTINATION_SERVER


def resolve_choice(
    *,
    local_flag: bool = False,
    connect_url: str | None = None,
    override_value: str | None = None,
    resumed: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve ``(destination, api_url)`` from the non-interactive inputs.

    Precedence: explicit flags (``--local`` / ``--connect URL``), then the
    :data:`DESTINATION_OVERRIDE` environment value, then a resumed run's
    stored destination. Returns ``(None, None)`` when nothing chose one —
    the interactive wizard then shows the picker, and the flag-driven lane
    keeps today's ``--env``/``--api-url`` semantics. Raises ``ValueError``
    for an unusable override value.
    """
    if local_flag:
        return DESTINATION_LOCAL, None
    url = str(connect_url or "").strip()
    if url:
        return destination_for_api_url(url), url
    overridden = _parse_override(override_value)
    if overridden is not None:
        return overridden
    stored = str(resumed or "").strip()
    if stored in DESTINATIONS:
        return stored, None
    return None, None


def _parse_override(value: str | None) -> tuple[str, str | None] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in (DESTINATION_LOCAL, DESTINATION_HOSTED):
        return text, None
    if text.startswith(("http://", "https://")):
        return destination_for_api_url(text), text
    if text == DESTINATION_SERVER:
        raise ValueError(
            f"{DESTINATION_OVERRIDE}={text!r} does not name a server; set it "
            "to the server URL instead (e.g. https://api.mycompany.com)"
        )
    raise ValueError(
        f"{DESTINATION_OVERRIDE} must be 'local', 'hosted', or a server URL; "
        f"got {text!r}"
    )


__all__ = [
    "DEFAULT_DESTINATION",
    "DEFAULT_SIGN_IN_ENV",
    "DESTINATIONS",
    "DESTINATION_HOSTED",
    "DESTINATION_LOCAL",
    "DESTINATION_OVERRIDE",
    "DESTINATION_SERVER",
    "ENV_PRODUCTION",
    "ENV_STAGE",
    "destination_for_api_url",
    "is_hosted_url",
    "resolve_choice",
]
