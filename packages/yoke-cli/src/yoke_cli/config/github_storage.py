"""Machine GitHub credential storage helpers."""

from __future__ import annotations

from yoke_cli.config import writer
from yoke_contracts.machine_config import schema as contract


class GitHubCredentialStorageError(RuntimeError):
    """GitHub machine credential storage failed."""


def store_credential_source(secret: str) -> dict[str, str]:
    return {
        "kind": contract.CREDENTIAL_KIND_TOKEN_FILE,
        "path": str(writer.store_github_token(secret)),
    }


__all__ = [
    "GitHubCredentialStorageError",
    "store_credential_source",
]
