"""Credential-file resolution for an HTTPS function relay."""

from pathlib import Path
from yoke_contracts.machine_config.schema import CREDENTIAL_KIND_TOKEN_FILE


class TransportError(RuntimeError):
    """The active connection cannot relay this request; message names the fix."""


def resolve_token(connection) -> str:
    source = connection.get("credential_source")
    source = source if isinstance(source, dict) else {}
    kind = str(source.get("kind") or "")
    if kind == CREDENTIAL_KIND_TOKEN_FILE:
        token_path = Path(str(source.get("path") or "")).expanduser()
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise TransportError(
                f"https credential token_file is unreadable: {exc}; "
                "repair it with `yoke auth set <env> TOKEN` "
                "(yoke status diagnoses the active config)"
            ) from exc
        if not token:
            raise TransportError(f"https credential token_file {token_path} is empty")
        return token
    raise TransportError(
        "https transport requires credential_source.kind 'token_file' "
        f"(got {kind or 'nothing'}); store the actor token with "
        "`yoke auth set <env> TOKEN`"
    )
