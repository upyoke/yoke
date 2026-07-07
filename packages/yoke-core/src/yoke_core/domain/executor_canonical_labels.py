"""Canonical executor labels and known surface aliases.

Single source of truth for the canonical ``harness_id`` values that may
appear in ``harness_sessions.executor`` and for the surface-specific
aliases that must never appear there (surface aliases belong in
``harness_sessions.executor_display_name``).

Importers:

* :mod:`yoke_core.engines.doctor_hc_executor_canonicalization` — uses
  :data:`CANONICAL_HARNESS_IDS` as the basis for the leak filter.
* Future consolidation may route
  :mod:`runtime.harness.hook_helpers_identity`'s canonical-id literals
  through this module so the canonical-id set lives in exactly one
  place; that follow-up is tracked separately.
"""

from __future__ import annotations

from typing import Tuple


CANONICAL_HARNESS_IDS: Tuple[str, ...] = ("claude-code", "codex")
"""Canonical values for ``harness_sessions.executor``.

Active rows must carry one of these. Any other ``claude-*`` or ``codex-*``
value indicates a writer that bypassed ``canonicalize_executor``.
"""


KNOWN_SURFACE_LABELS: Tuple[str, ...] = (
    "claude-desktop",
    "claude-vscode",
    "codex-desktop",
    "codex-vscode",
)
"""Documented surface aliases used in operator orientation and tests.

The HC's runtime filter is pattern-based against
:data:`CANONICAL_HARNESS_IDS` so a new Yoke-family surface
(e.g. ``codex-jetbrains``, ``claude-cli``) still trips without a code
change here. These labels exist for test-fixture authoring and to
document which aliases are known to flow through the surface layer.
"""


__all__ = ["CANONICAL_HARNESS_IDS", "KNOWN_SURFACE_LABELS"]
