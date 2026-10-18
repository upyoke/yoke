"""Read each installed harness's machine-wide hooks for doctor.

Read-only: it reports what :mod:`yoke_harness.hooks.machine_hooks` would find,
with the setup step that repairs each state, and never writes a file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from yoke_contracts.harness_machine_hooks import HarnessMachineHooks
from yoke_harness.hooks.machine_hooks import (
    MachineHookResult,
    is_current,
    load_user_config,
    malformed_detail,
    owned_command_check,
    specs_for,
)
from yoke_harness.hooks.machine_hooks_render import is_machine_hook_entry

STATE_INSTALLED = "installed"
STATE_MISSING = "missing"
STATE_STALE = "stale"
STATE_MALFORMED = "malformed"
STATE_UNTRUSTED = "untrusted"


def inspect_machine_hooks(
    environ: Optional[Mapping[str, str]] = None,
) -> list[MachineHookResult]:
    """Per installed harness: installed, missing, stale, malformed or untrusted."""
    results: list[MachineHookResult] = []
    for spec in specs_for(None):
        path = spec.user_config_path(environ)
        if not spec.home_path(environ).is_dir():
            continue
        document, reason = load_user_config(path)
        if document is None:
            state, detail = STATE_MALFORMED, malformed_detail(path, reason)
        elif not any(
            is_machine_hook_entry(entry, spec)
            for entries in document.get("hooks", {}).values()
            for entry in entries
        ):
            state, detail = STATE_MISSING, "run `yoke setup` to install them"
        elif not is_current(spec, document):
            state, detail = STATE_STALE, "run `yoke setup` to refresh them"
        elif spec.trust == "codex_trusted_hash" and not _codex_trusted(spec, environ):
            state, detail = STATE_UNTRUSTED, "run `yoke setup` to trust them"
        else:
            state, detail = STATE_INSTALLED, ""
        results.append(MachineHookResult(spec.harness_id, str(path), state, detail))
    return results


def _codex_trusted(
    spec: HarnessMachineHooks, environ: Optional[Mapping[str, str]]
) -> bool:
    from yoke_contracts.codex_hook_trust_store import inspect_hook_file_trust
    from yoke_contracts.codex_user_hook_trust import owned_handler_suffixes

    hooks_path = spec.trust_config_path(environ)
    standing = inspect_hook_file_trust(
        hooks_path, config_path=spec.home_path(environ) / "config.toml"
    )
    document, _ = load_user_config(hooks_path)
    owned = owned_handler_suffixes(document or {}, owned_command_check(spec))
    return bool(owned) and owned <= set(standing.trusted)


__all__ = [
    "STATE_INSTALLED",
    "STATE_MALFORMED",
    "STATE_MISSING",
    "STATE_STALE",
    "STATE_UNTRUSTED",
    "inspect_machine_hooks",
]
