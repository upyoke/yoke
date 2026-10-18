"""Install, self-heal, inspect and remove Yoke's machine-wide hooks.

One owner for every harness: it reads the per-harness facts from
:mod:`yoke_contracts.harness_machine_hooks` and the entry shapes from
:mod:`yoke_harness.hooks.machine_hooks_render`. Setup, project install and
refresh, the per-hook self-heal, uninstall and doctor all call it.

It never creates a harness home (a missing home means the harness is not
installed here), never overwrites a config it cannot parse, and keeps every
entry and key it did not write. Yoke's entries go last in each event list so
the positions of a person's own handlers, which Codex trust is keyed by, do
not move.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.harness_machine_hooks import (
    HARNESS_MACHINE_HOOKS,
    HarnessMachineHooks,
)
from yoke_harness.hooks.machine_hooks_render import (
    is_machine_hook_entry,
    render_user_hook_entries,
)

INSTALLED = "installed"
UNCHANGED = "unchanged"
REMOVED = "removed"
DELETED = "deleted"
ABSENT = "absent"
MALFORMED = "machine_hooks_config_malformed"
TRUST_FAILED = "machine_hooks_trust_failed"
MACHINE_HOOKS_NOT_WRITTEN = "machine_hooks_not_written"

# Inspection states doctor reports.
STATE_INSTALLED = "installed"
STATE_MISSING = "missing"
STATE_STALE = "stale"
STATE_MALFORMED = "malformed"
STATE_UNTRUSTED = "untrusted"


def not_installed(spec: HarnessMachineHooks) -> str:
    return f"{spec.harness_id.removesuffix('-code')}_not_installed"


@dataclass(frozen=True)
class MachineHookResult:
    """What one harness's user config ended as, with any recovery step."""

    harness_id: str
    path: str
    outcome: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.outcome in (MALFORMED, TRUST_FAILED)

    def line(self) -> str:
        text = f"{self.harness_id}: {self.outcome} {self.path}"
        return f"{text} ({self.detail})" if self.detail else text


class MachineHooksError(RuntimeError):
    """A user config could not be changed; the message names the recovery."""


def _specs(harnesses: Optional[Iterable[str]]) -> list[HarnessMachineHooks]:
    ids = list(HARNESS_MACHINE_HOOKS) if harnesses is None else list(harnesses)
    return [HARNESS_MACHINE_HOOKS[harness_id] for harness_id in ids]


def _malformed_detail(path: Path, reason: str) -> str:
    return (
        f"{path} is not a hook config Yoke can edit: {reason}. Recovery: fix or "
        "move the file, then run `yoke setup` again"
    )


def _load(path: Path) -> tuple[Optional[dict[str, Any]], str]:
    """Return ``(document, malformed_reason)``; a missing file is ``({}, "")``."""
    if not path.exists():
        return {}, ""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(document, dict):
        return None, "the top level is not a JSON object"
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict) or any(
        not isinstance(value, list) for value in hooks.values()
    ):
        return None, "`hooks` is not an object of event lists"
    return document, ""


def _without_machine_entries(
    spec: HarnessMachineHooks, hooks: Mapping[str, list]
) -> dict[str, list]:
    kept: dict[str, list] = {}
    for event, entries in hooks.items():
        remaining = [entry for entry in entries if not is_machine_hook_entry(entry, spec)]
        if remaining or not entries:
            kept[event] = remaining
    return kept


def _render(spec: HarnessMachineHooks, document: dict[str, Any]) -> dict[str, Any]:
    updated = dict(document)
    hooks = _without_machine_entries(spec, document.get("hooks", {}))
    for event, entries in render_user_hook_entries(spec).items():
        hooks[event] = [*hooks.get(event, []), *entries]
    if spec.harness_id == "cursor":
        updated["version"] = int(updated.get("version") or 1)
    updated["hooks"] = hooks
    return updated


def _text(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def _write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.yoke-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _is_owned(spec: HarnessMachineHooks):
    return lambda command: is_machine_hook_entry({"command": command}, spec)


def _trust(spec: HarnessMachineHooks, environ: Optional[Mapping[str, str]], *, prune: bool) -> str:
    """Bring Codex trust in line with the user file; return a failure detail."""
    if spec.trust != "codex_trusted_hash":
        return ""
    from yoke_contracts.codex_hook_trust_toml import CodexHookTrustStoreError
    from yoke_contracts.codex_user_hook_trust import (
        mint_user_hook_trust,
        prune_user_hook_trust,
    )

    hooks_path = spec.user_config_path(environ)
    config_path = spec.home_path(environ) / "config.toml"
    try:
        if prune:
            prune_user_hook_trust(hooks_path, config_path)
        else:
            mint_user_hook_trust(hooks_path, config_path, is_owned=_is_owned(spec))
    except CodexHookTrustStoreError as exc:
        return (
            f"Codex hook trust was not written: {exc}. Recovery: fix "
            f"{config_path}, then run `yoke setup` again"
        )
    return ""


def ensure_harness(
    spec: HarnessMachineHooks,
    environ: Optional[Mapping[str, str]] = None,
    *,
    trust_when_unchanged: bool = True,
) -> MachineHookResult:
    """Converge one harness's user config with the rendered expectation."""
    path = spec.user_config_path(environ)
    if not spec.home_path(environ).is_dir():
        return MachineHookResult(spec.harness_id, str(path), not_installed(spec))
    document, reason = _load(path)
    if document is None:
        return MachineHookResult(
            spec.harness_id, str(path), MALFORMED, _malformed_detail(path, reason)
        )
    text = _text(_render(spec, document))
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    outcome = UNCHANGED if text == current else INSTALLED
    if outcome == INSTALLED:
        _write(path, text)
    if outcome == INSTALLED or trust_when_unchanged:
        failure = _trust(spec, environ, prune=False)
        if failure:
            return MachineHookResult(spec.harness_id, str(path), TRUST_FAILED, failure)
    return MachineHookResult(spec.harness_id, str(path), outcome)


def ensure_machine_hooks(
    harnesses: Optional[Iterable[str]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> list[MachineHookResult]:
    """Install the machine-wide hooks for every installed harness."""
    return [ensure_harness(spec, environ) for spec in _specs(harnesses)]


def ensure_machine_hooks_reported(
    harnesses: Optional[Iterable[str]] = None,
) -> tuple[list[str], list[str]]:
    """Install for setup and project install: ``(result lines, failures)``.

    Never raises: a refusal becomes a named failure line with its recovery.
    """
    try:
        results = ensure_machine_hooks(harnesses)
    except Exception as exc:  # noqa: BLE001 — reported, never fatal
        message = (
            f"{MACHINE_HOOKS_NOT_WRITTEN}: {exc}. Recovery: fix the named file, "
            "then run `yoke setup` again"
        )
        return [message], [message]
    return [r.line() for r in results], [r.line() for r in results if r.failed]


def ensure_machine_hooks_for_executor(executor: str, *, hook: str) -> None:
    """Per-hook self-heal: never blocks the hook, names any refusal."""
    try:
        from yoke_contracts.executor_labels import canonical_harness_id

        spec = HARNESS_MACHINE_HOOKS.get(canonical_harness_id(executor))
        if spec is None:
            return
        result = ensure_harness(spec, trust_when_unchanged=False)
        detail = result.detail if result.failed else ""
    except Exception as exc:  # noqa: BLE001 — hook transport must stay open
        detail = f"machine-wide hooks were not checked: {exc}"
    if detail:
        from yoke_contracts.hook_diagnostics import format_hook_diagnostic

        sys.stderr.write(format_hook_diagnostic(hook, detail) + "\n")


def remove_machine_hooks(
    environ: Optional[Mapping[str, str]] = None,
) -> list[MachineHookResult]:
    """Strip Yoke's entries from every user config; delete a file left empty."""
    results: list[MachineHookResult] = []
    for spec in _specs(None):
        path = spec.user_config_path(environ)
        document, reason = _load(path) if path.is_file() else (None, "")
        if document is None and not reason:
            results.append(MachineHookResult(spec.harness_id, str(path), ABSENT))
            continue
        if document is None:
            results.append(
                MachineHookResult(
                    spec.harness_id, str(path), MALFORMED, _malformed_detail(path, reason)
                )
            )
            continue
        hooks = document.get("hooks", {})
        kept = _without_machine_entries(spec, hooks)
        if kept == hooks:
            results.append(MachineHookResult(spec.harness_id, str(path), ABSENT))
            continue
        remaining = {key: value for key, value in document.items() if key not in ("hooks", "version")}
        if not any(kept.values()) and not remaining:
            path.unlink()
            outcome = DELETED
        else:
            _write(path, _text({**document, "hooks": kept}))
            outcome = REMOVED
        failure = _trust(spec, environ, prune=True)
        results.append(
            MachineHookResult(
                spec.harness_id, str(path), TRUST_FAILED if failure else outcome, failure
            )
        )
    return results


def inspect_machine_hooks(
    environ: Optional[Mapping[str, str]] = None,
) -> list[MachineHookResult]:
    """Per installed harness: installed, missing, stale, malformed or untrusted."""
    results: list[MachineHookResult] = []
    for spec in _specs(None):
        path = spec.user_config_path(environ)
        if not spec.home_path(environ).is_dir():
            continue
        document, reason = _load(path)
        if document is None:
            state, detail = STATE_MALFORMED, _malformed_detail(path, reason)
        elif not any(
            is_machine_hook_entry(entry, spec)
            for entries in document.get("hooks", {}).values()
            for entry in entries
        ):
            state, detail = STATE_MISSING, "run `yoke setup` to install them"
        elif _text(_render(spec, document)) != path.read_text(encoding="utf-8"):
            state, detail = STATE_STALE, "run `yoke setup` to refresh them"
        elif spec.trust == "codex_trusted_hash" and not _codex_trusted(spec, environ):
            state, detail = STATE_UNTRUSTED, "run `yoke setup` to trust them"
        else:
            state, detail = STATE_INSTALLED, ""
        results.append(MachineHookResult(spec.harness_id, str(path), state, detail))
    return results


def _codex_trusted(spec: HarnessMachineHooks, environ: Optional[Mapping[str, str]]) -> bool:
    from yoke_contracts.codex_hook_trust_store import inspect_hook_file_trust
    from yoke_contracts.codex_user_hook_trust import owned_handler_suffixes

    hooks_path = spec.user_config_path(environ)
    standing = inspect_hook_file_trust(
        hooks_path, config_path=spec.home_path(environ) / "config.toml"
    )
    document, _ = _load(hooks_path)
    owned = owned_handler_suffixes(document or {}, _is_owned(spec))
    return bool(owned) and owned <= set(standing.trusted)


__all__ = [
    "MachineHookResult",
    "MachineHooksError",
    "ensure_harness",
    "ensure_machine_hooks",
    "ensure_machine_hooks_for_executor",
    "inspect_machine_hooks",
    "not_installed",
    "remove_machine_hooks",
]
