"""Same-origin anonymous collection and server-verified attribution cookies."""

from http.cookies import SimpleCookie
from urllib.parse import urlsplit

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


def attribution_cookie(request):
    from yoke_core.frontend_events.events_cookie import AttributionCookie

    _, _, secret = read_collector_identity()
    return AttributionCookie(secret, request.url.hostname)


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
