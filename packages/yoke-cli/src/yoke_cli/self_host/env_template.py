"""The self-host bundle's ``.env``: runtime knobs Docker Compose interpolates.

Values here are never secrets — Compose interpolates ``$`` inside them, so
generated credentials ride owner-only files under ``secrets/`` instead.
"""

from __future__ import annotations

from yoke_contracts.first_admin_name import ADMIN_NAME_ENV
from yoke_contracts.github_app_public import (
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
)
from yoke_contracts.self_host_bootstrap_output import API_PUBLISH_ENV


def env_text(*, image: str, publish_spec: str, admin_name: str) -> str:
    """Render the bundle's ``.env``; ``admin_name`` is already validated."""
    return (
        "# Yoke self-host runtime knobs; docker compose reads this file for\n"
        "# ${...} interpolation. Secrets never live here — compose\n"
        "# interpolates $ inside these values; generated credentials ride\n"
        "# owner-only files under secrets/ instead.\n"
        f"YOKE_SERVER_IMAGE={image}\n"
        "# Host publish spec for the API port. The default binds loopback\n"
        "# only; to serve your network set e.g. 0.0.0.0:8765 — behind TLS.\n"
        f"{API_PUBLISH_ENV}={publish_spec}\n"
        "# Trusted TLS proxy IPs/CIDRs, comma-separated; empty trusts none.\n"
        "# Use the peer address seen inside core, never * on an exposed port.\n"
        "YOKE_API_TRUSTED_PROXIES=127.0.0.1\n"
        "# The installer's name. First boot creates this universe's first\n"
        "# admin as this person and refuses to start without it.\n"
        f"{ADMIN_NAME_ENV}={admin_name}\n"
        "\n"
        "# --- Browser sign-in via your OIDC provider (optional) ----------\n"
        "# Uncomment and fill to enable the web sign-in door; leave\n"
        "# commented to keep it disabled (API tokens work either way).\n"
        "# Walkthrough: docs/self-host-browser-sign-in.md.\n"
        "#YOKE_OIDC_ISSUER=https://accounts.example.com\n"
        "#YOKE_OIDC_CLIENT_ID=yoke\n"
        "# The server's external base URL; the callback path is derived\n"
        "# from it (register <base>/v1/auth/oidc/callback at the provider).\n"
        "#YOKE_OIDC_REDIRECT_URL=https://yoke.internal\n"
        "# The client secret rides an owner-only file (never a .env value):\n"
        "#   printf '%s\\n' '<client-secret>' > secrets/oidc-client-secret\n"
        "#   chmod 600 secrets/oidc-client-secret\n"
        "# then uncomment this line:\n"
        "#YOKE_OIDC_CLIENT_SECRET_FILE=/dev/shm/yoke-runtime-secrets/yoke-oidc-client-secret\n"
        "\n"
        "# --- GitHub App server automation (optional) ------------------\n"
        "# Configure one App for this control plane. The issuer and API URL\n"
        "# are nonsecret; the App private key remains a host-opened file.\n"
        "#YOKE_GITHUB_APP_ISSUER=123456\n"
        "#YOKE_GITHUB_APP_API_URL=https://api.github.com\n"
        "# Optional product-facing Connect profile: set every field or\n"
        "# leave every field commented to advertise GitHub as unavailable.\n"
        f"#{GITHUB_APP_WEB_URL_ENV}=https://github.com\n"
        f"#{GITHUB_APP_ID_ENV}=123456\n"
        f"#{GITHUB_APP_CLIENT_ID_ENV}=Iv23example\n"
        f"#{GITHUB_APP_SLUG_ENV}=yoke-self-hosted\n"
        "# Install or rotate through Yoke's atomic owner-only ingress:\n"
        "#   chmod 600 /secure/path/app-key.pem\n"
        "#   yoke self-host init --dir . --protect-existing \\\n"
        "#     --github-app-private-key /secure/path/app-key.pem\n"
        "# then uncomment this line:\n"
        "#YOKE_GITHUB_APP_PRIVATE_KEY_FILE="
        "/dev/shm/yoke-runtime-secrets/yoke-github-app-private-key\n"
    )


__all__ = ["env_text"]
