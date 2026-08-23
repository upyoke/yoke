"""Read Codex hook files through the canonical trust-identity normalizer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from yoke_contracts.codex_hook_trust import normalized_codex_hook_hashes


class CodexHookIdentityError(ValueError):
    """The hooks document cannot produce Codex-compatible trust identities."""


def codex_hook_hashes(hooks_path: Path) -> Dict[str, str]:
    """Return normalized hashes for the handlers in ``hooks_path``."""
    try:
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexHookIdentityError(str(exc)) from exc
    return codex_hook_hashes_from_document(document)


def codex_hook_hashes_from_document(document: object) -> Dict[str, str]:
    """Return normalized hashes or reject a malformed hooks document."""
    hashes = normalized_codex_hook_hashes(document)
    if hashes is None:
        raise CodexHookIdentityError(
            "hooks document cannot produce Codex-compatible trust identities"
        )
    return hashes


__all__ = [
    "CodexHookIdentityError",
    "codex_hook_hashes",
    "codex_hook_hashes_from_document",
]
