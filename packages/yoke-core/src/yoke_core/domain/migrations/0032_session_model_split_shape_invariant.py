"""Hold the session model split to the schema shape it actually owes.

``0030_session_model_requested_split`` also asserted, as a standing
invariant, that no ``harness_sessions`` row carries a served ``model``
without a ``requested_model``. That was true the moment its backfill
committed and false from the next registration onward: the split's own
contract makes a null requested column mean *no ask was recorded*, which is
the correct and permanent state for a session nobody launched with an
explicit model. Live builds write such rows during ordinary operation, so
every fleet preflight after the first live traffic re-proved that assertion
against rows it was never about, failed, and blocked the release train on a
fact the schema never claimed.

The bytes of a history entry are permanent — each database records the
digest of the entry it applied, and rewriting the module in place would make
every converged install refuse to boot on a content mismatch. So the
correction lands here instead. This entry retires 0030's invariants and
restates the durable half: the requested and served columns exist, and
``model`` is nullable so "nothing was attested" stays expressible. That is
exactly what the split owes any database that applied it.

Nothing is transformed. 0030's backfill already ran everywhere, and the rows
that now violate its assertion are correct as they stand; deriving a request
from a served value would invent an ask nobody recorded.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _column_exists,
    _column_is_not_null,
    _table_exists,
)


RETIRES_INVARIANTS = ("0030_session_model_requested_split",)

TABLE = "harness_sessions"
SPLIT_COLUMNS = (
    "requested_model",
    "requested_reasoning_effort",
    "requested_context_window_tokens",
    "reasoning_effort",
    "context_window_tokens",
)
ATTESTED_COLUMN = "model"


def apply(conn: Any) -> None:
    """Transform nothing: the correction is which invariants stand."""


def invariants(conn: Any) -> None:
    """Prove the split's schema shape wherever the session table exists."""
    if not _table_exists(conn, TABLE):
        return
    for column in SPLIT_COLUMNS:
        assert _column_exists(conn, TABLE, column), (
            f"{TABLE}.{column} is missing after the requested/served split"
        )
    assert not _column_is_not_null(conn, TABLE, ATTESTED_COLUMN), (
        f"{TABLE}.{ATTESTED_COLUMN} must stay nullable so a session with no "
        "provider attestation can say so"
    )


__all__ = [
    "ATTESTED_COLUMN",
    "RETIRES_INVARIANTS",
    "SPLIT_COLUMNS",
    "TABLE",
    "apply",
    "invariants",
]
