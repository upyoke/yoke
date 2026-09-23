"""Bind recorded session usage to its start-time catalog revision.

One place resolves rates, so every surface that shows a dollar figure —
the board, the session roster, the workbench — shows the same one. The
reference is the single representation of what a model costs; this module
adds no table of its own and no default rate. Raw token capture is independent:
a session records what it consumed even when no one researched its price.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional

from yoke_contracts.model_reference import lookup_api_price
from yoke_contracts.model_reference_records import ModelRecord
from yoke_contracts.session_usage_cost import SessionCost, session_cost
from yoke_contracts.session_usage_facts import SessionUsage


def reference_prices(
    served_model: str, records: tuple[ModelRecord, ...]
) -> Optional[object]:
    """Return the reference's price record for a served model id.

    The served id is resolved through the reference's own model lookup
    first, so an alias or a variant spelling reaches the same record as
    its canonical id rather than reading as an unknown model. ``None``
    means the reference does not know this model, or knows it but has no
    researched prices for it.
    """
    return lookup_api_price(served_model, records)


def estimated_session_cost(
    usage: Optional[SessionUsage], revision: Mapping[str, Any]
) -> SessionCost:
    """Price cumulative usage against the revision effective at first registration."""
    records = tuple(revision["records"])
    cost = session_cost(usage, lambda model: reference_prices(model, records))
    return replace(
        cost,
        revision_id=str(revision["revision_id"]),
        revision_effective_at=str(revision["effective_at"]),
    )


__all__ = [
    "estimated_session_cost",
    "reference_prices",
]
