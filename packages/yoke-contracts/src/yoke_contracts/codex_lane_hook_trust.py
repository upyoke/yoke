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

Worktree trust is mirrored, never minted: only content identical after CRLF
normalization receives a current source hash. Lane setup refreshes trust for the Yoke-authored
main-checkout file before mirroring it. Content changed only in a lane needs
the operator's own Codex trust decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional, Tuple

from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_contracts.codex_hook_trust import (
    CodexHookIdentityError,
    codex_hook_hashes,
)
from yoke_contracts.codex_hook_trust_store import (
    HOOKS_RELATIVE_PATH,
)
from yoke_contracts.codex_hook_trust_toml import (
    TRUSTED_HASH_KEY,
    all_hook_entries,
    append_hook_entries,
    mutate,
    entries_for as _entries_for,
    read_trust_state as _read_trust_state,
)
from yoke_contracts.harness_folder_trust import codex_path_spellings


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
    untrusted_paths: Tuple[str, ...] = ()

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
        parts = [self.blocked_reason] if self.blocked_reason else []
        if self.missing:
            parts.append(f"{len(self.missing)} untrusted: {', '.join(self.missing)}")
        if self.stale:
            parts.append(f"{len(self.stale)} modified: {', '.join(self.stale)}")
        if self.untrusted_paths:
            parts.append(f"affected paths: {', '.join(self.untrusted_paths)}")
        return "; ".join(parts)


def hooks_file_for(checkout: str) -> Path:
    """Return the Codex hooks path a checkout or worktree exposes."""
    return Path(checkout) / HOOKS_RELATIVE_PATH


def trust_entries_for(
    hooks_path: Path,
    *,
    config_path: Optional[Path] = None,
) -> Dict[str, str]:
    """Return trust entries keyed to the literal ``hooks_path``.

    Codex does not resolve symlinks before keying, so callers must pass
    the path Codex would see — never ``Path.resolve()`` of a tracked
    ``.codex/hooks.json`` symlink. The returned suffix-to-hash map is
    compared with the normalized current handlers by machine inventory;
    an empty map means this path has never been trusted.
    """
    state, reason = _read_trust_state(config_path or codex_config_path())
    if reason:
        return {}
    return _entries_for(state, hooks_path)


def _same_content(left: Path, right: Path) -> Tuple[bool, str]:
    """Compare bytes after folding Git's CRLF checkout line endings."""
    try:
        left_content = left.read_bytes().replace(b"\r\n", b"\n")
        right_content = right.read_bytes().replace(b"\r\n", b"\n")
        return left_content == right_content, ""
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
    )
    if source_stale:
        return _blocked(
            result,
            f"source_hook_trust_stale: Run `yoke project refresh` in {source_checkout}.",
        )
    if not source_trusted:
        return _blocked(result, REASON_SOURCE_UNTRUSTED)
    if not target_hooks.exists():
        return _blocked(result, f"{REASON_NO_TARGET_HOOKS}: {target_hooks}")

    identical, read_error = _same_content(source_hooks, target_hooks)
    if read_error:
        return _blocked(result, read_error)

    try:
        target_hashes = codex_hook_hashes(target_hooks)
    except CodexHookIdentityError as exc:
        return _blocked(result, f"{REASON_UNREADABLE_HOOKS}: {exc}")
    already, missing, stale = set(), set(), set()
    affected_paths = []
    paths = codex_path_spellings(target_hooks)
    for path in paths:
        target_entries = _entries_for(state, Path(path))
        target_trusted, target_stale = _current_trust(target_entries, target_hashes)
        target_missing = source_trusted.keys() - target_entries.keys()
        already.update(
            key
            for key, digest in source_trusted.items()
            if target_trusted.get(key) == digest
        )
        missing.update(target_missing)
        stale.update(target_stale)
        if len(paths) > 1 and (target_missing or target_stale):
            affected_paths.append(path)
    result = _with(
        result,
        already_trusted=tuple(sorted(already)),
        missing=tuple(sorted(missing)),
        stale=tuple(sorted(stale)),
        untrusted_paths=tuple(affected_paths),
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
    written unless the two hooks files match after CRLF normalization.
    """
    path = config_path or codex_config_path()
    result = inspect_hook_trust(source_checkout, worktree, config_path=path)
    if result.blocked_reason or result.stale or not result.missing:
        return result

    def plan(text, document):
        current = all_hook_entries(document)
        source = Path(result.source_hooks_path)
        identical, read_error = _same_content(source, Path(result.target_hooks_path))
        if not identical:
            raise ValueError(read_error or REASON_CONTENT_DIFFERS)
        expected = codex_hook_hashes(source)
        source_digests = {}
        for suffix in result.source_trusted:
            digest = expected.get(suffix)
            entry = current.get(f"{source}:{suffix}")
            if (
                not digest
                or not isinstance(entry, dict)
                or entry.get(TRUSTED_HASH_KEY) != digest
            ):
                raise ValueError(
                    "source hook trust changed; refresh the checkout and retry"
                )
            source_digests[suffix] = digest
        mirrored = set()
        for spelling in codex_path_spellings(result.target_hooks_path):
            additions = {}
            for suffix, digest in source_digests.items():
                target_key = f"{spelling}:{suffix}"
                if target_key not in current:
                    additions[suffix] = digest
                    continue
                entry = current[target_key]
                if not isinstance(entry, dict) or entry.get(TRUSTED_HASH_KEY) != digest:
                    raise ValueError(
                        f"hook trust changed for {target_key}; re-trust in Codex"
                    )
            if additions:
                text = append_hook_entries(text, Path(spelling), additions)
                mirrored.update(additions)
        return text, tuple(sorted(mirrored))

    try:
        mirrored = mutate(path, plan)
    except (OSError, RuntimeError, ValueError) as exc:
        return _with(result, write_error=f"could not update {path}: {exc}")
    return _with(result, mirrored=mirrored, missing=(), untrusted_paths=())


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
