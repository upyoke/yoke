"""Bind recorded session usage to the shared model reference's prices.

One place resolves rates, so every surface that shows a dollar figure —
the board, the session roster, the workbench — shows the same one. The
reference is the single representation of what a model costs; this module
adds no table of its own and no default rate.

The reference is a sibling capability that may not be installed in every
build. When it is absent the cost is ``unavailable`` naming the exact
lookup that was missing, so an operator reads a stated gap rather than a
zero. Raw token capture is deliberately independent of all of it: a
session records what it consumed whether or not its model has ever been
priced, and a stale or missing reference never blocks that recording.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.session_usage_cost import SessionCost, session_cost
from yoke_contracts.session_usage_facts import SessionUsage


#: The reference lookups this module consumes, named in the message a
#: missing reference produces so the reader knows what to install.
PRICE_LOOKUP_PATH = (
    "yoke_contracts.model_reference.lookup_model_reference / lookup_api_price"
)

REFERENCE_MISSING_REASON = f"model price reference not available ({PRICE_LOOKUP_PATH})"


def reference_prices(served_model: str) -> Optional[object]:
    """Return the reference's price record for a served model id.

    The served id is resolved through the reference's own model lookup
    first, so an alias or a variant spelling reaches the same record as
    its canonical id rather than reading as an unknown model. ``None``
    means the reference does not know this model, or knows it but has no
    researched prices for it.
    """
    try:
        from yoke_contracts.model_reference import (
            lookup_api_price,
            lookup_model_reference,
        )
    except ImportError:
        return None
    lookup = lookup_model_reference(served_model)
    record = (
        getattr(lookup, "record", None)
        if getattr(lookup, "researched", False)
        else None
    )
    model_id = getattr(record, "model_id", "") if record is not None else ""
    return lookup_api_price(model_id or served_model)


def estimated_session_cost(usage: Optional[SessionUsage]) -> SessionCost:
    """Price one session's usage against the shared reference."""
    if usage is None or not usage.models:
        return session_cost(usage, reference_prices)
    if not _reference_installed():
        return SessionCost(reason=REFERENCE_MISSING_REASON)
    return session_cost(usage, reference_prices)


def _reference_installed() -> bool:
    """True when the shared model reference is importable in this build."""
    try:
        import yoke_contracts.model_reference  # noqa: F401
    except ImportError:
        return False
    return True


__all__ = [
    "PRICE_LOOKUP_PATH",
    "REFERENCE_MISSING_REASON",
    "estimated_session_cost",
    "reference_prices",
]
