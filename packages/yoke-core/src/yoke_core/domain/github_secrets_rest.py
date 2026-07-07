"""GitHub Actions secrets — encrypt + push via REST (libsodium sealed box).

GitHub's secrets API only accepts ciphertexts encrypted with the repo's
ed25519 public key via libsodium's sealed-box construction. This module
fetches the public key, encrypts the secret value, and PUTs it. List +
delete are also covered for symmetry with the legacy shellouts.

Used by bootstrap_project_setup to push SSH-key / SSH-host / SSH-user
secrets during project initialization; by bootstrap_project_verify and
validate_webapp_pipeline_checks_remote to verify presence of expected
secrets; and by doctor_hc_worktrees_gh_project to list configured
secrets for health checks.

Token resolution flows through resolve_project_github_auth — never
through host gh credentials. PyNaCl provides the libsodium binding;
pinned at >=1.5.0,<2.0 in pyproject.toml.
"""

from __future__ import annotations

import base64
from typing import Iterable

from nacl.public import PublicKey, SealedBox

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)


# ---------------------------------------------------------------------------
# Repo-secret operations
# ---------------------------------------------------------------------------


def fetch_public_key(repo: str, *, token: str) -> tuple[str, str]:
    """Return ``(key_id, base64_public_key)`` for ``repo`` (e.g. "owner/name")."""
    req = RestRequest(method="GET", path=f"/repos/{repo}/actions/secrets/public-key")
    resp = request_with_retry(req, token=token)
    body = resp.body or {}
    return str(body["key_id"]), str(body["key"])


def encrypt_secret(public_key_b64: str, plaintext: str) -> str:
    """Encrypt ``plaintext`` against the base64-encoded ed25519 ``public_key_b64``.

    Returns the base64-encoded sealed-box ciphertext GitHub expects.
    """
    key_bytes = base64.b64decode(public_key_b64)
    sealed = SealedBox(PublicKey(key_bytes))
    ciphertext = sealed.encrypt(plaintext.encode("utf-8"))
    return base64.b64encode(ciphertext).decode("ascii")


def set_repo_secret(repo: str, name: str, value: str, *, token: str) -> None:
    """Create or update a repo Actions secret.

    Raises :class:`RestTransportError` (or a subclass) on terminal failure.
    """
    key_id, key_b64 = fetch_public_key(repo, token=token)
    encrypted = encrypt_secret(key_b64, value)
    req = RestRequest(
        method="PUT",
        path=f"/repos/{repo}/actions/secrets/{name}",
        body={"encrypted_value": encrypted, "key_id": key_id},
    )
    request_with_retry(req, token=token)


def list_repo_secret_names(repo: str, *, token: str) -> list[str]:
    """Return the list of Actions secret names configured on ``repo``."""
    req = RestRequest(
        method="GET",
        path=f"/repos/{repo}/actions/secrets",
        query={"per_page": "100"},
    )
    resp = request_with_retry(req, token=token)
    body = resp.body or {}
    secrets: Iterable[dict] = body.get("secrets", [])  # type: ignore[assignment]
    return [str(entry["name"]) for entry in secrets if "name" in entry]


def repo_secret_exists(repo: str, name: str, *, token: str) -> bool:
    """Return True iff ``name`` is set as an Actions secret on ``repo``."""
    return name in list_repo_secret_names(repo, token=token)


__all__ = [
    "encrypt_secret",
    "fetch_public_key",
    "list_repo_secret_names",
    "repo_secret_exists",
    "set_repo_secret",
]
