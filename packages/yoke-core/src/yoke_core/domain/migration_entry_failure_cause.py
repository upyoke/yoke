"""Name what actually broke when a migration entry fails.

An entry rarely reports its own failure accurately, and the applier's caller
only ever sees one final line, so the root cause has to be carried in the
message rather than left on ``__context__`` for a log surface that does not
print it.
"""

from __future__ import annotations

from yoke_core.domain.migration_apply_contract import MigrationApplyError


class EntryFailed(MigrationApplyError):
    """An entry that could not be applied, named by what actually broke.

    Most entries wrap their SQL in ``try``/``finally`` to restore a guard they
    crossed, and on Postgres the statement that really failed aborts the
    transaction — so the cleanup in the ``finally`` fails too, with a generic
    "transaction is aborted", and that replaces the real error. The original
    survives only on ``__context__``, which no log surface prints and which
    the reports reaching an operator routinely truncate away. Carrying the
    root cause in this message keeps it legible down to a single final line.
    """


def root_cause(exc: BaseException) -> BaseException:
    """The deepest exception behind this one, following causes and contexts."""
    seen = {id(exc)}
    root = exc
    while True:
        deeper = root.__cause__ or root.__context__
        if deeper is None or id(deeper) in seen:
            return root
        seen.add(id(deeper))
        root = deeper


def failure_reason(exc: BaseException) -> str:
    """One line naming the root cause and, when different, what surfaced it."""
    root = root_cause(exc)
    if root is exc:
        return f"{type(exc).__name__}: {exc}"
    return f"{type(root).__name__}: {root} (surfaced as {type(exc).__name__})"


__all__ = ["EntryFailed", "failure_reason", "root_cause"]
