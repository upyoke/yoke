"""Repair saved connections whose token a machine sign-in just revoked.

One live credential per machine per server is the server's rule, so a sign-in
under one connection name revokes the token saved under another. Only the
server can say which saved tokens that hit: a token with no machine binding
survives rotation and must stay where it is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import server_connect, writer
from yoke_contracts.machine_config import secret_files as machine_secrets

AUTHENTICATION_REVOKED = "authentication_revoked"
_PROBE_TIMEOUT_S = 5.0


def repair_revoked_connections(
    env: str, *, api_url: str, path: str | Path | None = None
) -> dict[str, list[str]]:
    """Repoint revoked same-server connections at ``env``'s credential.

    Returns ``credential_shared_with`` (repointed) and ``credential_unverified``
    (the server could not say, so the connection was left unchanged).
    """
    candidates = writer.same_server_credentials(env, path=path)
    verdicts: dict[str, bool | None] = {}
    revoked: dict[str, dict[str, str]] = {}
    unverified: list[str] = []
    for name, source in candidates.items():
        token_path = source["path"]
        if token_path not in verdicts:
            verdicts[token_path] = _token_revoked(api_url, token_path)
        verdict = verdicts[token_path]
        if verdict is None:
            unverified.append(name)
        elif verdict:
            revoked[name] = source
    shared = writer.share_credential(env, revoked, path=path) if revoked else []
    return {
        "credential_shared_with": sorted(shared),
        "credential_unverified": sorted(unverified),
    }


def _token_revoked(api_url: str, token_path: str) -> bool | None:
    """True when revoked, False when it works, None when the check failed."""
    try:
        token: Any = machine_secrets.read_secret_file(token_path, "token")
        server_connect.verify_server_identity(
            api_url, token=token, timeout_s=_PROBE_TIMEOUT_S
        )
    except server_connect.ServerIdentityError as exc:
        return True if exc.code == AUTHENTICATION_REVOKED else None
    except (machine_secrets.MachineSecretError, server_connect.ServerConnectError):
        return None
    return False


__all__ = ["AUTHENTICATION_REVOKED", "repair_revoked_connections"]
