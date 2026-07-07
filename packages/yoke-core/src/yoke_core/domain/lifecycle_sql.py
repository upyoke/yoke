"""SQL fragment helpers and human-readable display labels for status tokens.

Owns the SQL ``IN``-clause helpers used by raw-SQL escape-hatch callers and
the ``display_label`` rendering used by the board, scheduler summaries, and
operator-facing prose. Imports the terminal-status frozensets from
``lifecycle_predicates``; the ``lifecycle`` front door re-exports each public
name for backwards-compatible imports.
"""

from __future__ import annotations

from yoke_core.domain.lifecycle_predicates import TASK_TERMINAL_SUCCESS

# ---------------------------------------------------------------------------
# SQL fragment helpers (parity with shell _sql_*_list functions)
# ---------------------------------------------------------------------------


def sql_terminal_success_list() -> str:
    """Return SQL IN-clause fragment for terminal success statuses."""
    return "'done'"


def sql_task_terminal_success_list() -> str:
    """Return SQL IN-clause fragment for epic-task terminal success statuses.

    Distinct from item-level ``sql_terminal_success_list``
    (``'done'``).
    """
    return ",".join(f"'{s}'" for s in sorted(TASK_TERMINAL_SUCCESS))


def sql_terminal_failure_list() -> str:
    """Return SQL IN-clause fragment for terminal failure statuses."""
    return "'stopped','failed'"


def sql_terminal_list() -> str:
    """Return SQL IN-clause fragment for all terminal statuses."""
    return "'done','stopped','failed'"


# ---------------------------------------------------------------------------
# Display label helpers
# ---------------------------------------------------------------------------


def display_label(status: str) -> str:
    """Return the human-readable display label for a status token.

    Stored tokens are hyphenated (e.g., ``refining-idea``); display labels use
    spaces (e.g., ``refining idea``).  Non-hyphenated tokens pass through
    unchanged.  The Python implementation is the canonical definition.
    """
    return status.replace("-", " ")
