"""Runtime-settings adapter for the long-command polling lint.

Hosts the mode helpers in a leaf sibling so the evaluate module can
import them without creating an import cycle when the hook is invoked
via ``python -m yoke_core.domain.lint_long_command_polling``.

The entry-point re-exports both functions so external callers continue
to find them at ``yoke_core.domain.lint_long_command_polling``.
"""

from __future__ import annotations


def _read_lint_mode(payload: object | None = None) -> str:
    """Resolve enforcement mode from the single lint_config registry.

    Sourced from ``.yoke/lint-config`` via ``lint_config`` so this guard shares
    the one operator surface and the protected-guard clamp.
    """
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload("lint_long_command_polling", payload)
