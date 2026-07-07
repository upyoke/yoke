"""Compatibility seam for legacy DB query failure detection.

The implementation-facing module is now
:mod:`yoke_core.domain.db_error_hook_query_failure`. This file remains
importable because current callers and tests still use
``detect_sqlite_failure`` as a stable historical symbol while current
callers move to ``detect_db_query_failure``.
"""

from __future__ import annotations

from yoke_core.domain.db_error_hook_query_failure import (
    detect_db_query_failure,
    detect_sqlite_failure,
)

__all__ = ("detect_db_query_failure", "detect_sqlite_failure")
