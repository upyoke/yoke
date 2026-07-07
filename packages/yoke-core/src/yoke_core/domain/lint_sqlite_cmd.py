"""Compatibility front door for the stable database-command guard hook.

Keep this module path and the ``lint-sqlite-cmd`` telemetry/check id importable:
historical ``HarnessToolCallDenied`` rows and field-note attribution name them.
The implementation now lives behind the neutral
:mod:`yoke_core.domain.lint_db_cmd` module so readers can distinguish legacy
ids from current DB-command policy ownership.
"""

from __future__ import annotations

import sys

from yoke_core.domain.denial_field_note_footer import append_field_note_footer  # noqa: F401
from yoke_core.domain import lint_db_cmd as _impl
from runtime.harness.hook_runner.types import HookContext, HookDecision, Outcome

HOOK_POLICY_SOURCE = _impl.HOOK_POLICY_SOURCE
LEGACY_HOOK_ID = _impl.LEGACY_HOOK_ID
run_hook = _impl.run_hook

# Private compatibility names retained for existing tests and operator
# diagnostics that drive the legacy module path directly.
_resolve_db_fallback = _impl._resolve_db_fallback
_parse_payload = _impl._parse_payload
_extract_command = _impl._extract_command
_deny_reason_from_output = _impl._deny_reason_from_output
_emit_legacy_denial = _impl._emit_legacy_denial
_emit_sqlite_denial = _impl._emit_legacy_denial
_build_context_from_payload = _impl._build_context_from_payload

__all__ = [
    "HOOK_POLICY_SOURCE",
    "LEGACY_HOOK_ID",
    "evaluate",
    "main",
    "run_hook",
]


def evaluate(record: HookContext) -> HookDecision:
    """Legacy module typed entry; delegates to the neutral implementation."""
    return _impl.evaluate(
        record,
        run_hook_func=run_hook,
        db_fallback_resolver=_resolve_db_fallback,
    )


def main() -> int:
    """CLI entry for deployed hook configs that still import this module."""
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    payload = _parse_payload(raw)
    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
