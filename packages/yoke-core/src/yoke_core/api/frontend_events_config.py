"""Same-origin anonymous collection and server-verified attribution cookies."""

import ipaddress
import logging
from functools import cache
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from publicsuffixlist import PublicSuffixList

from yoke_core.domain.frontend_events_storage import read_collector_identity

EVENTS_PATH = "/api/events"
ATTRIBUTION_PATH = EVENTS_PATH + "/attribution"
HANDOFF_PATH = ATTRIBUTION_PATH + "/handoff"
REDEEM_PATH = HANDOFF_PATH + "/redeem"
CONFIG_PATH = EVENTS_PATH + "/config"
COLLECTOR_PATHS = frozenset(
    {EVENTS_PATH, ATTRIBUTION_PATH, CONFIG_PATH, HANDOFF_PATH, REDEEM_PATH}
)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_log = logging.getLogger(__name__)


def collector_origin(request):
    """Compare Origin to the actual serving authority, never a forwarded IP."""
    parts = urlsplit(str(request.base_url))
    if parts.scheme != "https" and parts.hostname not in LOOPBACK_HOSTS:
        raise ValueError(
            "collector_https_required: serve remote workbenches over HTTPS; "
            "set YOKE_API_TRUSTED_PROXIES to the TLS proxy IPs/CIDRs in the "
            "self-host bundle .env and restart with yoke self-host init "
            "--dir PATH --protect-existing --start"
        )
    return f"{parts.scheme}://{parts.netloc}"


@cache
def _public_suffixes():
    return PublicSuffixList()


def site_domain(host):
    """The registrable domain owning ``host``, so the apex and siblings are internal.

    app.upyoke.com and app.stage.upyoke.com both own upyoke.com; a self-hosted
    yoke.acme.co.uk owns acme.co.uk. An IP or a host with no registrable
    domain (localhost, a single-label LAN name) is its own site.
    """
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return _public_suffixes().privatesuffix(host) or host


def attribution_cookie(request):
    from yoke_core.frontend_events.events_cookie import AttributionCookie

    _, _, secret = read_collector_identity()
    return AttributionCookie(secret, site_domain(request.url.hostname))


def cookie_name(request):
    from yoke_core.frontend_events.events_cookie import COOKIE_NAME

    if request.url.scheme == "http" and request.url.hostname in LOOPBACK_HOSTS:
        # Loopback has no HTTPS door. HttpOnly cookies are port-named, as the
        # workbench session gate is, so two local universes do not share state.
        return f"events_attribution_{request.url.port or 80}"
    _, key, _ = read_collector_identity()
    return f"{COOKIE_NAME}_{key[:16]}"  # Isolate tenants sharing one serving host.


def cookie_input(request):
    from yoke_core.frontend_events.events_cookie import COOKIE_NAME

    parsed = SimpleCookie(request.headers.get("cookie", ""))
    name = cookie_name(request)
    return f"{COOKIE_NAME}={parsed[name].value}" if name in parsed else ""


def cookie_output(request, header):
    from yoke_core.frontend_events.events_cookie import COOKIE_NAME

    name = cookie_name(request)
    header = header.replace(COOKIE_NAME, name, 1)
    if request.url.scheme == "http" and request.url.hostname in LOOPBACK_HOSTS:
        header = header.replace("; Secure", "")
    return header


def cleared_attribution_cookie(request):
    """The Set-Cookie header that drops this browser's visitor id at sign-out."""
    from yoke_core.frontend_events.events_cookie import COOKIE_NAME

    return cookie_output(
        request, f"{COOKIE_NAME}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax"
    )


def verified_attribution(request):
    """Sign-in may read only the server-signed attribution record, never events."""
    if not any(
        name.startswith(("__Host-events_attribution", "events_attribution_"))
        for name in request.cookies
    ):
        return None
    if not cookie_input(request):
        return None
    return attribution_cookie(request).read(cookie_input(request))


def sign_in_attribution(request):
    """The verified attribution a sign-in may use; None, named, when unreadable."""
    try:
        return verified_attribution(request)
    except Exception:
        _log.warning(
            "attribution_unavailable: restore analytics capture; signing in without attribution",
            exc_info=True,
        )
        return None


def link_sign_in_visitor(conn, attribution, actor_id):
    """Link the signing-in browser's verified visitor id to its actor.

    Sign-in proceeds either way; a refused or failed link is named in the
    server log, and a refusal is also recorded on the visitor's link row.
    """
    from yoke_core.domain.actor_visitor_links import record_visitor_link

    if not attribution:
        return None
    try:
        result = record_visitor_link(
            conn, visitor_id=attribution["visitor_id"], actor_id=actor_id
        )
    except Exception:
        conn.rollback()
        _log.warning(
            "visitor_link_unavailable: restore the boot-converged actor_visitor_links "
            "table; this sign-in's browser stays unlinked until its next sign-in",
            exc_info=True,
        )
        return None
    if result.refused:
        _log.warning(
            "%s: visitor %s stays linked to actor %s and was not linked to actor %s; "
            "sign out on the shared browser so the next person starts a fresh visitor id",
            result.outcome,
            result.visitor_id,
            result.linked_actor_id,
            result.actor_id,
        )
    return result
