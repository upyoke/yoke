"""API import surface for :mod:`yoke_core.domain.oidc_config`."""

from yoke_core.domain.oidc_config import (
    OIDC_ALLOW_UNVERIFIED_EMAIL_ENV as OIDC_ALLOW_UNVERIFIED_EMAIL_ENV,
    OIDC_CLIENT_ID_ENV as OIDC_CLIENT_ID_ENV,
    OIDC_CLIENT_SECRET_ENV as OIDC_CLIENT_SECRET_ENV,
    OIDC_CLIENT_SECRET_FILE_ENV as OIDC_CLIENT_SECRET_FILE_ENV,
    OIDC_ISSUER_ENV as OIDC_ISSUER_ENV,
    OIDC_REDIRECT_URL_ENV as OIDC_REDIRECT_URL_ENV,
    OidcConfig as OidcConfig,
    OidcConfigError as OidcConfigError,
    OidcError as OidcError,
    __all__ as __all__,
    callback_url as callback_url,
    resolve_oidc_config as resolve_oidc_config,
)
