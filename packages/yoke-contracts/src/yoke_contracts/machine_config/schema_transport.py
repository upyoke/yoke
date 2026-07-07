"""Transport constants shared by machine-config contract helpers."""

DEFAULT_TRANSPORT = "local-postgres"
TRANSPORT_HTTPS = "https"
TRANSPORTS = frozenset({DEFAULT_TRANSPORT, TRANSPORT_HTTPS})
POSTGRES_TRANSPORTS = frozenset({DEFAULT_TRANSPORT})
PRODUCT_CLIENT_TRANSPORTS = frozenset({TRANSPORT_HTTPS})
