"""Client-safe TOML table edits for Codex's path-keyed trust store."""

from __future__ import annotations

import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from filelock import FileLock, Timeout

from yoke_contracts.refusal_recovery import compose_refusal

TRUSTED_HASH_KEY = "trusted_hash"
CONFIG_LOCK_TIMEOUT_SECONDS = 10
_TABLE_MARKER = "__yoke_hook_trust_table_marker__"
_Result = TypeVar("_Result")


class CodexHookTrustStoreError(RuntimeError):
    """A config mutation was refused without corrupting Codex state."""


def read_config(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        document = tomllib.loads(text) if text.strip() else {}
    except OSError as exc:
        raise CodexHookTrustStoreError(
            compose_refusal(
                f"could not read Codex config {path}: {exc}.",
                recovery="check the file permissions, then retry.",
            )
        ) from exc
    except UnicodeError as exc:
        raise CodexHookTrustStoreError(
            compose_refusal(
                f"Codex config {path} is not UTF-8.",
                recovery="repair the file encoding, then retry.",
            )
        ) from exc
    except ValueError as exc:
        location = re.search(
            r"\(at (?:line \d+, column \d+|end of document)\)$", str(exc)
        )
        detail = f" {location.group()}" if location else ""
        raise CodexHookTrustStoreError(
            compose_refusal(
                f"{path} is not valid TOML{detail}.",
                recovery="repair the file, then retry.",
            )
        ) from exc
    return text, dict(document)


def read_trust_state(config: Path) -> tuple[dict[str, str], str]:
    """Return valid hook hash pairs plus a non-raising inspection reason."""
    if not config.exists():
        return {}, f"Codex config not present: {config}"
    try:
        _, document = read_config(config)
    except CodexHookTrustStoreError as exc:
        return {}, f"Codex config could not be read: {exc}"
    state = all_hook_entries(document)
    return {
        str(key): str(entry[TRUSTED_HASH_KEY])
        for key, entry in state.items()
        if isinstance(entry, dict)
        and isinstance(entry.get(TRUSTED_HASH_KEY), str)
        and entry[TRUSTED_HASH_KEY]
    }, ""


def entries_for(state: dict[str, str], hooks_path: Path) -> dict[str, str]:
    prefix = f"{hooks_path}:"
    return {
        key[len(prefix) :]: value
        for key, value in state.items()
        if key.startswith(prefix)
    }


def all_hook_entries(document: dict[str, Any]) -> dict[str, Any]:
    hooks = document.get("hooks") or {}
    state = hooks.get("state") if isinstance(hooks, dict) else {}
    return dict(state) if isinstance(state, dict) else {}


def project_entries(document: dict[str, Any]) -> dict[str, Any]:
    projects = document.get("projects") or {}
    return dict(projects) if isinstance(projects, dict) else {}


def hook_path(key: str) -> Optional[str]:
    parts = key.rsplit(":", 3)
    if (
        len(parts) != 4
        or not parts[0]
        or not parts[1]
        or not all(part.isdigit() for part in parts[2:])
    ):
        return None
    return parts[0]


def path_is_gone(value: str) -> bool:
    path = Path(value).expanduser()
    if not path.is_absolute():
        return False
    try:
        return not path.exists()
    except OSError:
        return False


def append_hook_entries(text: str, hooks_path: Path, entries: dict[str, str]) -> str:
    body = text
    if body and not body.endswith(("\n", "\r")):
        body += "\n"
    for suffix in sorted(entries):
        key = _toml_string(f"{hooks_path}:{suffix}")
        digest = _toml_string(entries[suffix])
        body += f"\n[hooks.state.{key}]\n{TRUSTED_HASH_KEY} = {digest}\n"
    return body


def filter_tables(
    text: str, hook_keys: set[str], project_paths: set[str]
) -> tuple[str, int, int]:
    """Remove exact hook/project table blocks while retaining other bytes."""
    lines = text.splitlines(keepends=True)
    headers = [(index, _table_document(line)) for index, line in enumerate(lines)]
    headers = [(index, doc) for index, doc in headers if doc is not None]
    if not headers:
        return text, 0, 0
    chunks = ["".join(lines[: headers[0][0]])]
    removed_hooks, removed_projects = set(), set()
    for offset, (start, document) in enumerate(headers):
        end = headers[offset + 1][0] if offset + 1 < len(headers) else len(lines)
        identity = _table_identity(document)
        if identity and identity[0] == "hook" and identity[1] in hook_keys:
            removed_hooks.add(identity[1])
            continue
        if identity and identity[0] == "project" and identity[1] in project_paths:
            removed_projects.add(identity[1])
            continue
        chunks.append("".join(lines[start:end]))
    return "".join(chunks), len(removed_hooks), len(removed_projects)


def mutate(
    path: Path,
    planner: Callable[[str, dict[str, Any]], tuple[str, _Result]],
) -> _Result:
    """Serialize read, plan and atomic publication for one physical config.

    FileLock removes the lock sidecar on release, and a waiter that opened the
    unlinked file retries. A sidecar that could not be removed is recorded for
    ``yoke uninstall`` instead of being left behind unowned.
    """
    target = path
    try:
        target = path.resolve(strict=False)
        lock_path = target.with_name(f".{target.name}.yoke.lock")
        created_lock = not lock_path.exists()
        try:
            with FileLock(
                str(lock_path), timeout=CONFIG_LOCK_TIMEOUT_SECONDS, mode=0o600
            ):
                return _mutate_locked(target, planner)
        finally:
            if created_lock and lock_path.exists():
                _record_lock_sidecar(lock_path)
    except Timeout as exc:
        raise CodexHookTrustStoreError(
            compose_refusal(
                f"Codex config is busy: {target}.",
                recovery="wait for the other configuration update to finish, then retry.",
            )
        ) from exc
    except OSError as exc:
        raise CodexHookTrustStoreError(
            compose_refusal(
                f"could not update {target}: {exc}.",
                recovery="check the directory permissions and available space, then retry.",
            )
        ) from exc


def _record_lock_sidecar(lock_path: Path) -> None:
    # Imported here: the ledger reads machine config this module never needs.
    from yoke_contracts import harness_settings_ledger as ledger

    # A record failure leaves only an empty lock file, never a broken config.
    ledger.record(ledger.created_file_entry(lock_path))


def _mutate_locked(
    path: Path,
    planner: Callable[[str, dict[str, Any]], tuple[str, _Result]],
) -> _Result:
    text, document = read_config(path)
    updated, result = planner(text, document)
    if updated == text:
        return result
    try:
        tomllib.loads(updated)
    except ValueError as exc:
        raise CodexHookTrustStoreError(
            compose_refusal(
                f"refusing invalid Codex config update for {path}.",
                recovery="keep the original file and report the writer failure.",
            )
        ) from exc
    target = path
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.yoke-", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        if target.exists() and target.read_text(encoding="utf-8") != text:
            raise CodexHookTrustStoreError(
                compose_refusal(
                    f"codex_config_changed: {target} changed during the update.",
                    recovery="retry after Codex finishes writing its configuration.",
                )
            )
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return result


def _toml_string(value: str) -> str:
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise CodexHookTrustStoreError(
            f"refusing to write control characters: {value!r}"
        )
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _table_document(line: str) -> Optional[dict[str, Any]]:
    stripped = line.strip()
    if not stripped.startswith("["):
        return None
    try:
        document = tomllib.loads(f"{stripped}\n{_TABLE_MARKER} = true\n")
    except ValueError:
        return None
    return dict(document) if _contains_marker(document) else None


def _contains_marker(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get(_TABLE_MARKER) is True or any(
            _contains_marker(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_marker(child) for child in value)
    return False


def _table_identity(document: dict[str, Any]) -> tuple[str, str] | None:
    hooks = document.get("hooks") or {}
    state = hooks.get("state") if isinstance(hooks, dict) else {}
    if isinstance(state, dict):
        for key, value in state.items():
            if _contains_marker(value):
                return "hook", str(key)
    projects = document.get("projects") or {}
    if isinstance(projects, dict):
        for key, value in projects.items():
            if _contains_marker(value):
                return "project", str(key)
    return None


__all__ = [
    "CodexHookTrustStoreError",
    "TRUSTED_HASH_KEY",
    "all_hook_entries",
    "append_hook_entries",
    "entries_for",
    "filter_tables",
    "hook_path",
    "mutate",
    "path_is_gone",
    "project_entries",
    "read_config",
    "read_trust_state",
]
