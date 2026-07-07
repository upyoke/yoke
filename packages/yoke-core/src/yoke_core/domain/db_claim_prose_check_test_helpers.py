"""Shared helpers for the db_claim_prose_check pytest suites.

Split out of the original ``test_db_claim_prose_check.py`` so each authored
test file stays under the 350-line limit. Lives outside the ``test_*.py``
collection pattern so pytest does not pick it up as a test module.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_mutation_profile import (
    REVIEWED_NEGATIVE_FIELD,
    REVIEWED_VALIDATED_AT_FIELD,
)


def _reviewed_none_profile_json(
    *,
    validated_at: str = "2026-04-24T16:35:36Z",
) -> str:
    """Canonical stamped reviewed-none profile JSON (fixture shape)."""
    return json.dumps(
        {
            "state": "none",
            REVIEWED_NEGATIVE_FIELD: True,
            REVIEWED_VALIDATED_AT_FIELD: validated_at,
        },
        sort_keys=True,
    )


def _stamp_reviewed_none_profile(
    db_conn: Any,
    *,
    item_id: int,
    validated_at: str = "2026-04-24T16:35:36Z",
) -> None:
    """Write the stamped reviewed-none profile onto an existing item row.

    Fixture shorthand for the state the ``db_claim.amend`` workflow
    leaves behind after a ``state="none"`` amendment. Tests that prove
    the writer itself call :func:`yoke_core.domain.db_claim.amend`
    directly instead.
    """
    p = "%s" if db_backend.connection_is_postgres(db_conn) else "?"
    db_conn.execute(
        f"UPDATE items SET db_mutation_profile = {p} WHERE id = {p}",
        (_reviewed_none_profile_json(validated_at=validated_at), item_id),
    )
    db_conn.commit()
