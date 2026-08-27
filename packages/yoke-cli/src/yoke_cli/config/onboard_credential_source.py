"""Where an onboarding run's connection credential comes from.

``build_report`` records two related facts about the credential backing the
connection it is about to write: the *plan* (the machine-local file the token
will be read from once written) and the *source* (how this invocation was
handed the token — an argument, an already-existing file, or nothing at all).
Both are report fields, not writes; the credential itself is written elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import secrets as machine_secrets


def credential_plan(cfg_path: Path, env_name: str) -> dict[str, Any]:
    """Return where the env's token will live once the connection is written."""
    return {
        "kind": "token_file",
        "path": str(machine_secrets.secret_path(env_name, "token")),
    }


def invocation_source(
    *,
    token: str | None,
    token_file: str | Path | None,
    source_kind: str,
) -> dict[str, Any]:
    """Return how this invocation was handed its token, if it was handed one."""
    if token_file is not None:
        return {"kind": "token_file", "path": str(Path(token_file).expanduser())}
    if token:
        return {"kind": source_kind}
    return {"kind": "missing"}


__all__ = ["credential_plan", "invocation_source"]
