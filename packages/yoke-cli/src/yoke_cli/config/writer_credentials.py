"""Credential input and storage helpers for machine-config writers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_cli.config import secrets as machine_secrets
from yoke_contracts.machine_config import schema as contract


class CredentialWriteError(RuntimeError):
    """Credential inputs are invalid or cannot be stored."""


def credential_from_inputs(
    env: str,
    *,
    token: Optional[str],
    token_file: Optional[str],
    token_stdin: bool,
    dsn: Optional[str],
    dsn_file: Optional[str],
    dsn_stdin: bool,
    require_one: bool,
) -> dict[str, str]:
    chosen = [name for name, given in (
        ("token", bool(token)),
        ("--token-file", bool(token_file)),
        ("--token-stdin", token_stdin),
        ("--dsn", bool(dsn)),
        ("--dsn-file", bool(dsn_file)),
        ("--dsn-stdin", dsn_stdin),
    ) if given]
    if len(chosen) > 1:
        raise CredentialWriteError(
            "credential sources are mutually exclusive: " + ", ".join(chosen)
        )
    if not chosen:
        if require_one:
            raise CredentialWriteError("exactly one credential source is required")
        return {}
    if token is not None:
        return _store_token(env, token)
    if token_file is not None:
        return _store_token(env, _read_secret_file(token_file, "token"))
    if token_stdin:
        return _store_token(env, _read_stdin_secret("token"))
    if dsn is not None:
        return _store_file_credential(env, contract.CREDENTIAL_KIND_DSN_FILE,
                                      dsn, "dsn")
    if dsn_file is not None:
        return _store_file_credential(
            env,
            contract.CREDENTIAL_KIND_DSN_FILE,
            _read_secret_file(dsn_file, "DSN"),
            "dsn",
        )
    return _store_file_credential(
        env,
        contract.CREDENTIAL_KIND_DSN_FILE,
        _read_stdin_secret("DSN"),
        "dsn",
    )


# A real Yoke API token is ~50 chars; a value far below this is almost
# certainly an accidental stub. Refuse to let one OVERWRITE an existing
# plausible token — the clobber that wiped a live ~/.yoke/secrets/prod.token
# and 401-ed every prod call. A short value on a fresh env is still allowed
# (there's no valid token to lose), so general credential-set flows are
# unaffected.
_MIN_PLAUSIBLE_TOKEN_LEN = 20


def _store_token(env: str, secret: str) -> dict[str, str]:
    _refuse_stub_overwriting_valid_token(env, secret)
    return _store_file_credential(
        env, contract.CREDENTIAL_KIND_TOKEN_FILE, secret, "token",
    )


def _refuse_stub_overwriting_valid_token(env: str, secret: str) -> None:
    if len(secret.strip()) >= _MIN_PLAUSIBLE_TOKEN_LEN:
        return  # plausible token — allowed (including rotation)
    try:
        existing = (
            machine_secrets.secret_path(env, "token")
            .read_text(encoding="utf-8")
            .strip()
        )
    except OSError:
        return  # no existing token — fresh write, allowed
    if len(existing) >= _MIN_PLAUSIBLE_TOKEN_LEN:
        raise CredentialWriteError(
            f"refusing to overwrite the existing {env} API token with an "
            f"implausibly short value ({len(secret.strip())} chars) — guards "
            "against an accidental stub clobbering a valid token; paste the "
            "full token, or remove the file first if this is intentional"
        )


def _store_file_credential(
    env: str,
    kind: str,
    secret: str,
    suffix: str,
) -> dict[str, str]:
    try:
        path = machine_secrets.store_machine_secret(env, suffix, secret)
    except machine_secrets.MachineSecretError as exc:
        raise CredentialWriteError(str(exc)) from exc
    return {"kind": kind, "path": str(path)}


def _read_secret_file(path: str | Path, label: str) -> str:
    try:
        return machine_secrets.read_secret_file(path, label)
    except machine_secrets.MachineSecretError as exc:
        raise CredentialWriteError(str(exc)) from exc


def _read_stdin_secret(label: str) -> str:
    try:
        return machine_secrets.read_stdin_secret(label)
    except machine_secrets.MachineSecretError as exc:
        raise CredentialWriteError(str(exc)) from exc


__all__ = ["CredentialWriteError", "credential_from_inputs"]
