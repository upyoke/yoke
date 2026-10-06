"""Configured residue cutoff for ``HC-claim-boundary-audit``.

The audit observes historical events on the canonical ledger. After the
writer-side prevention code is deployed, pre-fix rows remain in the
events table forever and would keep the doctor red. The cutoff suppresses
event ids strictly below the configured threshold; rows at or above the
threshold still surface as FAIL / WARN through the existing classification.

The cutoff value is read from machine config key
``hc_claim_boundary_audit_min_event_id``
via :mod:`yoke_core.domain.runtime_settings`. The default ``0`` means
"no cutoff" so a fresh project deploying the HC sees the full audit until
it sets the post-fix value explicitly.
"""

from __future__ import annotations

from yoke_core.domain.runtime_settings import get_int


_CONFIG_KEY = "hc_claim_boundary_audit_min_event_id"
_DEFAULT_CUTOFF = 0


def read_min_event_id_cutoff() -> int:
    """Return the configured minimum event id, or ``0`` (no cutoff)."""
    value = get_int(_CONFIG_KEY, _DEFAULT_CUTOFF)
    return value if value > 0 else 0


__all__ = ["read_min_event_id_cutoff"]
