"""Env-resolved configuration for the browser sign-in (OIDC) door.

The door is enabled by setting ``YOKE_OIDC_ISSUER``,
``YOKE_OIDC_CLIENT_ID``, a client secret (``YOKE_OIDC_CLIENT_SECRET_FILE``
preferred — an owner-only mounted file — with ``YOKE_OIDC_CLIENT_SECRET``
accepted for non-compose runs), and ``YOKE_OIDC_REDIRECT_URL`` (the
server's external base URL; the callback path is derived from it).

All unset means the door is cleanly disabled — zero behavior change for
tokened API clients. A partial set raises :class:`OidcConfigError`
naming the missing pieces so a half-wired door fails loudly instead of
half-working. No secret material is ever logged or embedded in raised
messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


OIDC_ISSUER_ENV = "YOKE_OIDC_ISSUER"
OIDC_CLIENT_ID_ENV = "YOKE_OIDC_CLIENT_ID"
OIDC_CLIENT_SECRET_FILE_ENV = "YOKE_OIDC_CLIENT_SECRET_FILE"
OIDC_CLIENT_SECRET_ENV = "YOKE_OIDC_CLIENT_SECRET"
OIDC_REDIRECT_URL_ENV = "YOKE_OIDC_REDIRECT_URL"
OIDC_ALLOW_UNVERIFIED_EMAIL_ENV = "YOKE_OIDC_ALLOW_UNVERIFIED_EMAIL"


class OidcError(RuntimeError):
    """Base class for browser sign-in door failures."""


class OidcConfigError(OidcError):
    """The door env config is partially set or unreadable."""


@dataclass(frozen=True)
class OidcConfig:
    """Resolved door configuration. ``client_secret`` is never logged."""

    issuer: str
    client_id: str
    client_secret: str
    redirect_base_url: str
    allow_unverified_email: bool

    @property
    def cookie_secure(self) -> bool:
        """Cookies get the ``Secure`` attribute when the door is served
        over https (derived from the configured external base URL, which
        is deterministic where the request scheme behind a proxy is not).
        """
        return self.redirect_base_url.lower().startswith("https://")


def _env_value(env: Mapping[str, str], key: str) -> str:
    """Read an env knob; blank counts as unset (compose passes empty
    strings through for unconfigured optional vars)."""
    return str(env.get(key) or "").strip()


def _read_secret_file(file_ref: str) -> str:
    try:
        content = Path(file_ref).read_text(encoding="utf-8")
    except OSError as exc:
        raise OidcConfigError(
            f"{OIDC_CLIENT_SECRET_FILE_ENV} names an unreadable file: "
            f"{exc.__class__.__name__}"
        ) from exc
    secret = content.strip()
    if not secret:
        raise OidcConfigError(
            f"{OIDC_CLIENT_SECRET_FILE_ENV} names an empty file"
        )
    return secret


def _require_secure_url(env_name: str, value: str) -> None:
    """Refuse a cleartext http:// URL to a non-loopback host.

    The client secret rides the token-exchange POST body and the whole
    id_token-verification chain (discovery, JWKS) runs against the issuer,
    so a cleartext hop to a remote host exposes credentials to a MITM.
    Loopback (a test stub / local dev provider) is exempt because the
    traffic never leaves the machine.
    """
    parts = urlsplit(value)
    if parts.scheme == "https":
        return
    host = (parts.hostname or "").lower()
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return
    raise OidcConfigError(
        f"{env_name} must be an https:// URL (http:// is accepted only for "
        "a loopback provider); refusing to run the sign-in flow in cleartext"
    )


def resolve_oidc_config(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[OidcConfig]:
    """Resolve the door config from the environment.

    Returns ``None`` when no door env var is set (door disabled). Raises
    :class:`OidcConfigError` naming the missing vars on a partial set.
    """
    if env is None:
        import os

        env = os.environ
    issuer = _env_value(env, OIDC_ISSUER_ENV).rstrip("/")
    client_id = _env_value(env, OIDC_CLIENT_ID_ENV)
    secret_file = _env_value(env, OIDC_CLIENT_SECRET_FILE_ENV)
    secret_inline = _env_value(env, OIDC_CLIENT_SECRET_ENV)
    redirect_base = _env_value(env, OIDC_REDIRECT_URL_ENV).rstrip("/")

    if not any((issuer, client_id, secret_file, secret_inline, redirect_base)):
        return None

    missing = []
    if not issuer:
        missing.append(OIDC_ISSUER_ENV)
    if not client_id:
        missing.append(OIDC_CLIENT_ID_ENV)
    if not secret_file and not secret_inline:
        missing.append(
            f"{OIDC_CLIENT_SECRET_FILE_ENV} (or {OIDC_CLIENT_SECRET_ENV})"
        )
    if not redirect_base:
        missing.append(OIDC_REDIRECT_URL_ENV)
    if missing:
        raise OidcConfigError(
            "OIDC sign-in is partially configured; missing: "
            + ", ".join(missing)
        )

    # The issuer is the one URL that MUST be https: discovery, JWKS, and the
    # token exchange that carries the client secret all hit it. (The redirect
    # base is only the browser's return address — no secret rides it — and its
    # scheme already drives the cookie Secure attribute via cookie_secure.)
    _require_secure_url(OIDC_ISSUER_ENV, issuer)

    secret = _read_secret_file(secret_file) if secret_file else secret_inline
    allow_unverified = _env_value(
        env, OIDC_ALLOW_UNVERIFIED_EMAIL_ENV,
    ).lower() in ("1", "true", "yes")
    return OidcConfig(
        issuer=issuer,
        client_id=client_id,
        client_secret=secret,
        redirect_base_url=redirect_base,
        allow_unverified_email=allow_unverified,
    )


def callback_url(config: OidcConfig) -> str:
    """The redirect_uri registered with the provider, derived from the
    configured external base URL."""
    from yoke_core.api.http_auth import OIDC_CALLBACK_PATH

    return config.redirect_base_url + OIDC_CALLBACK_PATH


__all__ = [
    "OIDC_ALLOW_UNVERIFIED_EMAIL_ENV",
    "OIDC_CLIENT_ID_ENV",
    "OIDC_CLIENT_SECRET_ENV",
    "OIDC_CLIENT_SECRET_FILE_ENV",
    "OIDC_ISSUER_ENV",
    "OIDC_REDIRECT_URL_ENV",
    "OidcConfig",
    "OidcConfigError",
    "OidcError",
    "callback_url",
    "resolve_oidc_config",
]
