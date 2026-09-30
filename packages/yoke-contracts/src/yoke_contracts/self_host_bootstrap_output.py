"""Safe self-host boot banners and dependency-light token wire validation."""

from __future__ import annotations

import re


TOKEN_PREFIX = "yoke_v1_"
TOKEN_BODY_LENGTH = 43
FIRST_BOOT_TOKEN_MARKER = "FIRST-BOOT ADMIN TOKEN"

#: Private socket descriptor passed through the bootstrap privilege drop.
FIRST_BOOT_TOKEN_FD_ENV = "YOKE_FIRST_BOOT_TOKEN_FD"
#: Operator token destination, written only by the host command.
FIRST_BOOT_TOKEN_HOST_PATH_ENV = "YOKE_FIRST_BOOT_TOKEN_HOST_PATH"
#: Host publish spec the bundle already carries, so the boot log can print the
#: real connect URL instead of a ``<server-url>`` placeholder.
API_PUBLISH_ENV = "YOKE_API_PUBLISH"

DEFAULT_API_PUBLISH_SPEC = "127.0.0.1:8765"
_LOOPBACK_HOST = "127.0.0.1"
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]"})

_TOKEN_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_]){re.escape(TOKEN_PREFIX)}"
    rf"[A-Za-z0-9]{{{TOKEN_BODY_LENGTH}}}(?![A-Za-z0-9])"
)


def is_api_token(value: str) -> bool:
    """Return whether ``value`` has the public Yoke API-token wire shape."""
    return _TOKEN_PATTERN.fullmatch(str(value or "")) is not None


def connect_url_from_publish_spec(publish_spec: str) -> str:
    """Turn a Compose host publish spec into a URL an operator can paste.

    A wildcard bind says where the server listens, not where this operator
    reaches it, so it resolves to loopback — the address that works on the
    host that ran the bundle.
    """
    spec = str(publish_spec or "").strip() or DEFAULT_API_PUBLISH_SPEC
    host, separator, port = spec.rpartition(":")
    if not separator or not port.isdigit():
        host, port = spec, ""
    host = host.strip().strip("[]")
    if host.lower() in _WILDCARD_HOSTS:
        host = _LOOPBACK_HOST
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}" if port else f"http://{host}"


def first_boot_admin_token_notice(*, host_path: str, connect_url: str) -> str:
    """Render the token-free boot banner naming where the credential landed."""
    return _framed(
        (
            f"  {FIRST_BOOT_TOKEN_MARKER} — written to an owner-only file, "
            "not to this log",
            "",
            f"      {host_path}",
            "",
            "  It is minted once and never rewritten. Connect a client with:",
            f"      yoke connect {connect_url} --token-stdin < {host_path}",
            "",
            "  Then remove that file; it is the only copy of the credential.",
        )
    )


def first_boot_admin_token_block(raw_token: str, *, connect_url: str) -> str:
    """Render the one-time credential block for a server with no token file.

    Only reached outside a Compose bundle, where there is nowhere else to
    put it. The banner says where the token now lives so the operator can
    clear it, instead of claiming a secrecy stdout cannot provide.
    """
    if not is_api_token(raw_token):
        raise ValueError("first-boot admin token has an invalid wire shape")
    return _framed(
        (
            f"  {FIRST_BOOT_TOKEN_MARKER} — minted once, printed here only",
            "",
            f"      {raw_token}",
            "",
            "  Save it now, then connect a client to this server with:",
            f"      yoke connect {connect_url} --token-stdin",
            "",
            "  This log now holds the token: clear it once the token is saved.",
        )
    )


def _framed(lines: tuple[str, ...]) -> str:
    border = "=" * 64
    return "\n".join((border, *lines, border))


def redact_api_tokens(value: str) -> str:
    """Remove raw Yoke API tokens from diagnostics and error messages."""
    return _TOKEN_PATTERN.sub("[Yoke API token redacted]", str(value or ""))


__all__ = [
    "API_PUBLISH_ENV",
    "DEFAULT_API_PUBLISH_SPEC",
    "FIRST_BOOT_TOKEN_FD_ENV",
    "FIRST_BOOT_TOKEN_HOST_PATH_ENV",
    "FIRST_BOOT_TOKEN_MARKER",
    "TOKEN_BODY_LENGTH",
    "TOKEN_PREFIX",
    "connect_url_from_publish_spec",
    "first_boot_admin_token_block",
    "first_boot_admin_token_notice",
    "is_api_token",
    "redact_api_tokens",
]
