"""Compatibility assembly point for the stable ``lint-sqlite-cmd`` policy.

The neutral implementation-facing assembly now lives in
:mod:`yoke_core.domain.lint_db_rules`. This module remains so legacy imports
and the old hook family name keep working while telemetry history continues to
use ``lint-sqlite-cmd``.
"""

from __future__ import annotations

from yoke_core.domain.denial_field_note_footer import append_field_note_footer  # noqa: F401
from yoke_core.domain.lint_db_rules import HOOK_POLICY_SOURCE

__all__ = ("HOOK_POLICY_SOURCE",)
