"""Mirror Codex hook trust from a checkout into its linked worktrees.

Codex records hook trust in ``$CODEX_HOME/config.toml`` under keys shaped
``[hooks.state."<hooks file>:<event>:<group>:<hook>"]``, each carrying a
``trusted_hash``. The key holds the *literal* path of the hooks file: Codex
does not resolve symlinks before keying, which is why a checkout's tracked
``.codex/hooks.json`` symlink is keyed at the symlink's own path rather than
at the file it points to.

A linked git worktree materializes that same tracked symlink at a different
absolute path, so it inherits none of the checkout's trust. Untrusted hooks
do not run — the only override is Codex's own dangerous bypass flag — so a
Codex thread working inside a worktree fires no hooks at all: no session
registration, no telemetry, no guardrails. Worktree provisioning closes that
gap by mirroring trust onto the worktree's path.

Trust is mirrored, never minted: only byte-identical content receives a hash
the operator already granted. Changed content needs the operator's own Codex
trust decision.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional, Tuple

from yoke_core.domain.codex_hook_trust_identity import (
    CodexHookIdentityError,
    codex_hook_hashes,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


#: Where a checkout exposes its Codex hooks, relative to the checkout root.
HOOKS_RELATIVE_PATH = os.path.join(".codex", "hooks.json")

_TRUSTED_HASH_KEY = "trusted_hash"

REASON_NO_CONFIG = "Codex config not present"
REASON_UNREADABLE_CONFIG = "Codex config could not be read"
REASON_NO_SOURCE_HOOKS = "source checkout exposes no Codex hooks file"
REASON_NO_TARGET_HOOKS = "worktree exposes no Codex hooks file"
REASON_UNREADABLE_HOOKS = "Codex hooks file could not be read"
REASON_SOURCE_UNTRUSTED = "source checkout holds no trusted Codex hook entries"
REASON_CONTENT_DIFFERS = (
    "worktree hooks content differs from the trusted source content"
)


@dataclass(frozen=True)
class HookTrustResult:
    """Codex hook-trust standing for one worktree.

    ``missing`` and ``stale`` are ``event:group:hook`` suffixes for absent
    worktree trust and hashes that no longer match a normalized handler.
    ``mirrored`` is what this call wrote.
    """

    target_hooks_path: str
    source_hooks_path: str = ""
    source_trusted: Tuple[str, ...] = ()
    already_trusted: Tuple[str, ...] = ()
    mirrored: Tuple[str, ...] = ()
    missing: Tuple[str, ...] = ()
    stale: Tuple[str, ...] = ()
    blocked_reason: str = ""
    write_error: str = ""

    @property
    def hooks_fire(self) -> bool:
        """True when every entry the source trusts is trusted here too."""
        return not (
            self.blocked_reason or self.write_error or self.missing or self.stale
        )

    @property
    def dead_zone(self) -> bool:
        """True when the source has trust and the worktree has none of it."""
        return bool(self.source_trusted) and not self.already_trusted

    def summary(self) -> str:
        """One-line human account of this worktree's standing."""
        if self.write_error:
            return self.write_error
        if self.hooks_fire:
            return f"{len(self.source_trusted)} hook entries trusted"
        parts = []
        if self.missing:
            parts.append(f"{len(self.missing)} untrusted: {', '.join(self.missing)}")
        if self.stale:
            parts.append(f"{len(self.stale)} modified: {', '.join(self.stale)}")
        if parts:
            return "; ".join(parts)
        return self.blocked_reason


def codex_config_path() -> Path:
    """Resolve the Codex config file this machine reads hook trust from."""
    home = os.environ.get("CODEX_HOME")
    root = Path(home) if home else Path.home() / ".codex"
    return root / "config.toml"


def hooks_file_for(checkout: str) -> Path:
    """Return the Codex hooks path a checkout or worktree exposes."""
    return Path(checkout) / HOOKS_RELATIVE_PATH


def _read_trust_state(config_path: Path) -> Tuple[Dict[str, str], str]:
    """Return every ``key -> trusted hash`` pair, plus a blocking reason."""
    if not config_path.exists():
        return {}, f"{REASON_NO_CONFIG}: {config_path}"
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError) as exc:
        return {}, f"{REASON_UNREADABLE_CONFIG}: {exc}"
    state = ((data.get("hooks") or {}).get("state")) or {}
    if not isinstance(state, dict):
        return {}, REASON_UNREADABLE_CONFIG
    pairs: Dict[str, str] = {}
    for key, entry in state.items():
        if isinstance(entry, dict):
            value = entry.get(_TRUSTED_HASH_KEY)
            if isinstance(value, str) and value:
                pairs[key] = value
    return pairs, ""


def _entries_for(state: Dict[str, str], hooks_path: Path) -> Dict[str, str]:
    """Map ``event:group:hook`` suffix -> trusted hash for one hooks file."""
    prefix = f"{hooks_path}:"
    return {
        key[len(prefix) :]: value
        for key, value in state.items()
        if key.startswith(prefix)
    }


def trust_entries_for(
    hooks_path: Path,
    *,
    config_path: Optional[Path] = None,
) -> Dict[str, str]:
    """Return trust entries keyed to the literal ``hooks_path``.

    Codex does not resolve symlinks before keying, so callers must pass
    the path Codex would see — never ``Path.resolve()`` of a tracked
    ``.codex/hooks.json`` symlink. Presence only: an empty map means
    this path has never been trusted. This does not hash file bytes.
    """
    state, reason = _read_trust_state(config_path or codex_config_path())
    if reason:
        return {}
    return _entries_for(state, hooks_path)


def _same_content(left: Path, right: Path) -> Tuple[bool, str]:
    """Compare two hooks files byte-for-byte, following symlinks."""
    try:
        return left.read_bytes() == right.read_bytes(), ""
    except OSError as exc:
        return False, f"{REASON_UNREADABLE_HOOKS}: {exc}"


def _current_trust(
    entries: Dict[str, str],
    expected: Dict[str, str],
) -> Tuple[Dict[str, str], Tuple[str, ...]]:
    """Split persisted entries into current trust and modified hashes."""
    current = {
        suffix: trusted_hash
        for suffix, trusted_hash in entries.items()
        if expected.get(suffix) == trusted_hash
    }
    stale = tuple(
        sorted(
            suffix
            for suffix, trusted_hash in entries.items()
            if suffix in expected and expected[suffix] != trusted_hash
        )
    )
    return current, stale


def inspect_hook_trust(
    source_checkout: str,
    worktree: str,
    *,
    config_path: Optional[Path] = None,
) -> HookTrustResult:
    """Report how much of the source's hook trust the worktree carries."""
    source_hooks = hooks_file_for(source_checkout)
    target_hooks = hooks_file_for(worktree)
    result = HookTrustResult(
        target_hooks_path=str(target_hooks),
        source_hooks_path=str(source_hooks),
    )

    state, reason = _read_trust_state(config_path or codex_config_path())
    if reason:
        return _blocked(result, reason)
    if not source_hooks.exists():
        return _blocked(result, f"{REASON_NO_SOURCE_HOOKS}: {source_hooks}")

    source_entries = _entries_for(state, source_hooks)
    if not source_entries:
        return _blocked(result, REASON_SOURCE_UNTRUSTED)
    try:
        source_hashes = codex_hook_hashes(source_hooks)
    except CodexHookIdentityError as exc:
        return _blocked(result, f"{REASON_UNREADABLE_HOOKS}: {exc}")
    source_trusted, source_stale = _current_trust(source_entries, source_hashes)
    result = _with(
        result,
        source_trusted=tuple(sorted(source_trusted)),
        stale=source_stale,
    )
    if not source_trusted and not source_stale:
        return _blocked(result, REASON_SOURCE_UNTRUSTED)
    if not target_hooks.exists():
        return _blocked(result, f"{REASON_NO_TARGET_HOOKS}: {target_hooks}")

    identical, read_error = _same_content(source_hooks, target_hooks)
    if read_error:
        return _blocked(result, read_error)

    target_entries = _entries_for(state, target_hooks)
    try:
        target_hashes = codex_hook_hashes(target_hooks)
    except CodexHookIdentityError as exc:
        return _blocked(result, f"{REASON_UNREADABLE_HOOKS}: {exc}")
    target_trusted, target_stale = _current_trust(target_entries, target_hashes)
    already = tuple(
        sorted(
            suffix
            for suffix, trusted_hash in source_trusted.items()
            if target_trusted.get(suffix) == trusted_hash
        )
    )
    missing = tuple(sorted(set(source_trusted) - set(target_entries)))
    stale = tuple(sorted(set(source_stale) | set(target_stale)))
    result = _with(
        result,
        already_trusted=already,
        missing=missing,
        stale=stale,
    )
    if not identical:
        return _blocked(result, REASON_CONTENT_DIFFERS)
    return result


def mirror_hook_trust(
    source_checkout: str,
    worktree: str,
    *,
    config_path: Optional[Path] = None,
) -> HookTrustResult:
    """Grant the worktree the trust the source already holds for this content.

    Idempotent: entries already present are left untouched, and nothing is
    written when the worktree's hook content is not byte-identical to the
    content whose trust is being mirrored.
    """
    path = config_path or codex_config_path()
    result = inspect_hook_trust(source_checkout, worktree, config_path=path)
    if result.blocked_reason or result.stale or not result.missing:
        return result

    state, reason = _read_trust_state(path)
    if reason:  # pragma: no cover - inspect already read the same file
        return _blocked(result, reason)
    source_entries = _entries_for(state, Path(result.source_hooks_path))

    try:
        block = _render_entries(
            result.target_hooks_path,
            {suffix: source_entries[suffix] for suffix in result.missing},
        )
    except ValueError as exc:
        return _with(result, write_error=str(exc))

    try:
        _append(path, block)
    except OSError as exc:
        return _with(result, write_error=f"could not update {path}: {exc}")
    return _with(result, mirrored=result.missing, missing=())


def _render_entries(hooks_path: str, entries: Dict[str, str]) -> str:
    """Render trust entries as appendable TOML tables."""
    lines = []
    for suffix in sorted(entries):
        key = _toml_string(f"{hooks_path}:{suffix}")
        value = _toml_string(entries[suffix])
        lines.append(f"\n[hooks.state.{key}]\n{_TRUSTED_HASH_KEY} = {value}\n")
    return "".join(lines)


def _toml_string(value: str) -> str:
    """Quote a value as a TOML basic string, refusing control characters."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"refusing to write control characters: {value!r}")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _append(config_path: Path, block: str) -> None:
    """Append trust entries, leaving every existing byte in place.

    Append-only on purpose: this is another tool's config file, so a
    read-modify-rewrite would risk losing whatever Codex wrote in between.
    """
    with config_path.open("a", encoding="utf-8") as handle:
        if config_path.stat().st_size and not _ends_with_newline(config_path):
            handle.write("\n")
        handle.write(block)


def _ends_with_newline(config_path: Path) -> bool:
    with config_path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) in (b"\n", b"\r")


def _blocked(result: HookTrustResult, reason: str) -> HookTrustResult:
    return _with(result, blocked_reason=reason)


def _with(result: HookTrustResult, **changes) -> HookTrustResult:
    return replace(result, **changes)


__all__ = [
    "HOOKS_RELATIVE_PATH",
    "HookTrustResult",
    "codex_config_path",
    "hooks_file_for",
    "inspect_hook_trust",
    "mirror_hook_trust",
    "trust_entries_for",
]
