"""compute_dispatch_status returns 'blocked' for flag rows.

`compute_dispatch_status` is the back-compat alias for
`classify_item_state`. The spec calls for an
explicit test surface for the alias so callers that adopted the new
name are covered separately from the rename.
"""

from __future__ import annotations

from yoke_core.domain.queries import (
    classify_item_state,
    compute_dispatch_status,
)


def test_alias_resolves_to_classify_item_state():
    assert compute_dispatch_status is classify_item_state


def test_alias_returns_blocked_for_flag_row():
    assert compute_dispatch_status(
        "implementing", frozen=False, blocked=True,
    ) == "blocked"


def test_alias_legacy_status_classifies_as_active_work():
    """Legacy ``status='blocked'`` rows (pre-cutover drift) classify as
    active_work — the dedicated ``HC-blocked-status-drift`` doctor check
    owns drift detection, not the live classifier."""
    assert compute_dispatch_status(
        "blocked", frozen=False, blocked=False,
    ) == "active_work"


def test_alias_distinguishes_flag_from_active_work():
    assert compute_dispatch_status(
        "implementing", frozen=False, blocked=False,
    ) == "active_work"


def test_alias_done_outranks_blocked():
    assert compute_dispatch_status(
        "done", frozen=False, blocked=True,
    ) == "done"
