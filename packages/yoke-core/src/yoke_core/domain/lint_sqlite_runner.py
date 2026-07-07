"""Compatibility runner for the stable ``lint-sqlite-cmd`` policy.

The implementation-facing runner is
:mod:`yoke_core.domain.lint_db_runner`. This module remains importable for
legacy tests and hook utilities while preserving the historical telemetry id.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_runner import run_hook

__all__ = ("run_hook",)
