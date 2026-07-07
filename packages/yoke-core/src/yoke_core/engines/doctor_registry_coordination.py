"""Coordination-lease health-check bundle.

Sibling registry slice carved out of :mod:`doctor_registry` so the parent file
stays under the 350-line authored-file limit, following the same pattern as
:mod:`doctor_registry_harness`. Owns the shared-operation lease + audit
provenance checks.

Public surface:

- :data:`COORDINATION_HEALTH_CHECKS` — ordered list spliced into the parent
  registry's ``HEALTH_CHECKS``.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_hc_coordination_leases import (
    hc_coordination_leases_stale_or_orphan,
    hc_coordination_leases_unmerged_source,
)
from yoke_core.engines.doctor_hc_path_claim_hard_blocks import (
    hc_path_claim_hard_blocks,
)
from yoke_core.engines.doctor_hc_path_claim_owner_kind import (
    hc_path_claim_owner_kind,
)
from yoke_core.engines.doctor_hc_routed_ownership import (
    hc_offer_envelope_clobber_lost_chain,
    hc_routed_ownership_live_frame_no_defense,
    hc_routed_ownership_non_terminal_release_still_schedulable,
)
from yoke_core.engines.doctor_hc_work_claim_status_mismatch import (
    hc_work_claim_status_mismatch,
)
from yoke_core.engines.doctor_registry_types import HealthCheck


COORDINATION_HEALTH_CHECKS: List[HealthCheck] = [
    HealthCheck(
        "coordination-leases-stale-or-orphan",
        "Stale or orphaned shared-operation leases",
        hc_coordination_leases_stale_or_orphan,
    ),
    HealthCheck(
        "coordination-leases-unmerged-source",
        "Completed live-apply audit rows whose source never merged",
        hc_coordination_leases_unmerged_source,
    ),
    HealthCheck(
        "path-claim-hard-blocks",
        "Over-hard activation edges authored from path-claim overlap",
        hc_path_claim_hard_blocks,
    ),
    HealthCheck(
        "path-claim-owner-kind",
        "Non-terminal path_claims rows with missing/invalid typed ownership",
        hc_path_claim_owner_kind,
    ),
    HealthCheck(
        "routed-ownership-live-frame-no-defense",
        "Live session with recent non-terminal release missing from defense",
        hc_routed_ownership_live_frame_no_defense,
    ),
    HealthCheck(
        "routed-ownership-non-terminal-release-still-schedulable",
        "Non-terminal release on a live owner whose item is still routable",
        hc_routed_ownership_non_terminal_release_still_schedulable,
    ),
    HealthCheck(
        "offer-envelope-clobber-lost-chain",
        "Historical chain_checkpoint clobber by a later offer write",
        hc_offer_envelope_clobber_lost_chain,
    ),
    HealthCheck(
        "work-claim-status-mismatch",
        "Item work-claims held on a status whose role mismatches the holder",
        hc_work_claim_status_mismatch,
    ),
]


__all__ = ["COORDINATION_HEALTH_CHECKS"]
