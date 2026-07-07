"""Joint lifecycle gates for the governed DB-mutation contract (governed DB-mutation contract).

Three gates compose the per-write validators (db_mutation_profile,
db_compatibility_attestation, db_mutation_compat_scanner,
migration_model_capability, deployment_flow validation) into the
lifecycle transitions where the contract is enforced:

* :func:`check_idea_to_refining_idea_gate`
  Profile schema + opportunistic scanner + attestation presence +
  model+flow cross-reference + cross-ticket overlap.  On pass, callers
  stamp ``db_compatibility_attestation.frozen_at`` to lock authored
  fields.  This gate proves *intent*, not artifacts: declared migration
  module slugs do not need to resolve to files on disk.  Apply-audit
  evidence is enforced at
  :func:`check_implementing_to_reviewing_implementation_gate`.

* :func:`check_implementing_to_reviewing_implementation_gate`
  Evidence gate: for each identifier in ``profile.migration_modules`` verify
  either the matching ``migration_audit`` row is ``state=completed``
  (apply intent on the configured runner) or a ``retired-without-apply: true``
  decision record exists at
  ``docs/archive/decisions/<module>.md`` (retire intent).

* :func:`check_polishing_implementation_to_implemented_gate`
  Thin verification: re-checks the same evidence and (for ``apply`` with
  live artifacts) the rollback backup file presence and the absence of
  stale in-progress audit rows.

Tickets whose ``db_mutation_profile.state`` is ``none`` pass every gate
trivially — absence-as-opt-out.

This module is the public front door — it imports each public name
directly from its canonical owner sibling (no two-hop indirection per
the re-export):

* :class:`GateOutcome` ← :mod:`...db_mutation_gate_shared`
* :func:`detect_overlap` ← :mod:`...db_mutation_gate_overlap`
* :func:`decision_record_path` ← :mod:`...db_mutation_gate_evidence`
* :func:`check_idea_to_refining_idea_gate`
  ← :mod:`...db_mutation_gate_idea`
* :func:`stamp_attestation_frozen_at` /
  :func:`clear_attestation_frozen_at`
  ← :mod:`...db_mutation_gate_attestation`
* :func:`check_implementing_to_reviewing_implementation_gate`
  ← :mod:`...db_mutation_gate_implementing`
* :func:`check_polishing_implementation_to_implemented_gate`
  ← :mod:`...db_mutation_gate_polish`
"""

from __future__ import annotations

from yoke_core.domain.db_mutation_gate_attestation import (
    clear_attestation_frozen_at,
    stamp_attestation_frozen_at,
)
from yoke_core.domain.db_mutation_gate_evidence import decision_record_path
from yoke_core.domain.db_mutation_gate_idea import (
    check_idea_to_refining_idea_gate,
)
from yoke_core.domain.db_mutation_gate_implementing import (
    check_implementing_to_reviewing_implementation_gate,
)
from yoke_core.domain.db_mutation_gate_overlap import detect_overlap
from yoke_core.domain.db_mutation_gate_polish import (
    check_polishing_implementation_to_implemented_gate,
)
from yoke_core.domain.db_mutation_gate_shared import GateOutcome


__all__ = [
    "GateOutcome",
    "check_idea_to_refining_idea_gate",
    "check_implementing_to_reviewing_implementation_gate",
    "check_polishing_implementation_to_implemented_gate",
    "clear_attestation_frozen_at",
    "decision_record_path",
    "detect_overlap",
    "stamp_attestation_frozen_at",
]
