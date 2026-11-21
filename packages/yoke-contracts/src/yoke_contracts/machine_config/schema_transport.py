"""Transport constants shared by machine-config contract helpers."""

DEFAULT_TRANSPORT = "local-postgres"
TRANSPORT_HTTPS = "https"
TRANSPORTS = frozenset({DEFAULT_TRANSPORT, TRANSPORT_HTTPS})
POSTGRES_TRANSPORTS = frozenset({DEFAULT_TRANSPORT})
PRODUCT_CLIENT_TRANSPORTS = frozenset({TRANSPORT_HTTPS})


def display_transport(connection: object) -> str:
    """The transport a person reads: ``http`` for an API client on plain HTTP.

    The stored ``https`` value names the Yoke API client whatever the URL
    scheme; human output shows the wire scheme instead. JSON keeps the stored
    value beside ``api_url``.
    """
    get = getattr(connection, "get", None)
    if get is None:
        return ""
    transport = str(get("transport") or "")
    if transport == TRANSPORT_HTTPS and str(get("api_url") or "").startswith("http://"):
        return "http"
    return transport
