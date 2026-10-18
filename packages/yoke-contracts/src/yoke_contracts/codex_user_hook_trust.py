"""Codex hook trust for the user-level ``$CODEX_HOME/hooks.json``.

Codex runs a hooks file only after its handlers carry a matching
``trusted_hash`` in ``$CODEX_HOME/config.toml``. Yoke trusts only the handlers
it wrote (the ``codex-user`` owner) and leaves the trust standing of every
handler a person added exactly as it was. It never creates ``$CODEX_HOME``:
a machine without Codex gets ``codex_not_installed`` and no writes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.codex_hook_trust import (
    CodexHookIdentityError,
    codex_hook_hashes_from_document,
)
from yoke_contracts.codex_hook_trust_store import TrustMutation
from yoke_contracts.codex_hook_trust_toml import (
    CodexHookTrustStoreError,
    TRUSTED_HASH_KEY,
    all_hook_entries,
    append_hook_entries,
    filter_tables,
    mutate,
)

CODEX_NOT_INSTALLED = "codex_not_installed"

# Codex trust labels per native event, in the hash suffix ``label:group:handler``.
_LABELS = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "user_prompt_submit",
    "PreToolUse": "pre_tool_use",
    "PermissionRequest": "permission_request",
    "PostToolUse": "post_tool_use",
    "Stop": "stop",
    "SessionEnd": "session_end",
}


def _hooks_document(hooks_path: Path) -> Optional[dict[str, Any]]:
    if not hooks_path.is_file():
        return None
    try:
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexHookTrustStoreError(f"could not read {hooks_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise CodexHookTrustStoreError(f"{hooks_path} is not a JSON object")
    return document


def owned_handler_suffixes(document: dict[str, Any], is_owned: Callable[[str], bool]) -> set[str]:
    """Hash suffixes whose handler command Yoke wrote."""
    owned: set[str] = set()
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return owned
    for event, label in _LABELS.items():
        groups = hooks.get(event)
        for group_index, group in enumerate(groups if isinstance(groups, list) else []):
            handlers = group.get("hooks") if isinstance(group, dict) else None
            for handler_index, handler in enumerate(handlers if isinstance(handlers, list) else []):
                command = handler.get("command") if isinstance(handler, dict) else None
                if isinstance(command, str) and is_owned(command):
                    owned.add(f"{label}:{group_index}:{handler_index}")
    return owned


def _plan(
    hooks_path: Path,
    selected: Path,
    write: dict[str, str],
    keep: Callable[[str], bool],
) -> Callable[[str, dict[str, Any]], tuple[str, TrustMutation]]:
    prefix = f"{hooks_path}:"

    def plan(text: str, document: dict[str, Any]) -> tuple[str, TrustMutation]:
        state = {
            key: str(value.get(TRUSTED_HASH_KEY) or "")
            for key, value in all_hook_entries(document).items()
            if isinstance(value, dict) and str(key).startswith(prefix)
        }
        current = {key[len(prefix) :]: digest for key, digest in state.items()}
        drop = {prefix + suffix for suffix in current if suffix in write or not keep(suffix)}
        if not drop and all(current.get(s) == d for s, d in write.items()):
            return text, TrustMutation(str(selected))
        filtered, removed, _ = filter_tables(text, drop, set())
        if removed != len(drop):
            raise CodexHookTrustStoreError(
                "hook trust uses an unsupported inline TOML layout"
            )
        updated = append_hook_entries(filtered, hooks_path, write)
        return updated, TrustMutation(
            str(selected),
            hook_entries_removed=removed,
            hook_entries_written=len(write),
            changed=True,
        )

    return plan


def mint_user_hook_trust(
    hooks_path: Path, config_path: Path, *, is_owned: Callable[[str], bool]
) -> TrustMutation:
    """Trust Yoke's handlers in the user hooks file; keep everyone else's."""
    if not config_path.parent.is_dir():
        return TrustMutation(str(config_path), skipped_reason=CODEX_NOT_INSTALLED)
    document = _hooks_document(hooks_path)
    if document is None:
        return TrustMutation(
            str(config_path), skipped_reason=f"Codex hooks file is absent: {hooks_path}"
        )
    try:
        hashes = codex_hook_hashes_from_document(document)
    except CodexHookIdentityError as exc:
        raise CodexHookTrustStoreError(f"could not normalize {hooks_path}: {exc}") from exc
    owned = owned_handler_suffixes(document, is_owned)
    write = {suffix: hashes[suffix] for suffix in owned}
    # A person's handler keeps its trust; a vanished position has nothing to trust.
    keep = lambda suffix: suffix in hashes and suffix not in owned  # noqa: E731
    return mutate(config_path, _plan(hooks_path, config_path, write, keep))


def prune_user_hook_trust(hooks_path: Path, config_path: Path) -> TrustMutation:
    """Drop trust for handler positions the user hooks file no longer holds."""
    if not config_path.is_file():
        return TrustMutation(str(config_path), skipped_reason=CODEX_NOT_INSTALLED)
    document = _hooks_document(hooks_path)
    hashes: dict[str, str] = {}
    if document is not None:
        try:
            hashes = codex_hook_hashes_from_document(document)
        except CodexHookIdentityError as exc:
            raise CodexHookTrustStoreError(
                f"could not normalize {hooks_path}: {exc}"
            ) from exc
    return mutate(
        config_path, _plan(hooks_path, config_path, {}, lambda suffix: suffix in hashes)
    )


__all__ = [
    "CODEX_NOT_INSTALLED",
    "mint_user_hook_trust",
    "owned_handler_suffixes",
    "prune_user_hook_trust",
]
