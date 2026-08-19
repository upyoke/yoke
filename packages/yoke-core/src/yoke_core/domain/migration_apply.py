"""Two-unit apply contract for governed DB migrations.

Per the governed-DB-mutation contract, an item-backed profile runs its
migration in two distinct units, separated by a mandatory operator
checkpoint:

**Rehearsal unit** (no lease, no backup, no authoritative mutation):

* ``planned → test_copy_created``: provision the model's validation
  surface.
* ``test_copy_created → test_applied``: apply the migration module to
  the validation DB.
* ``test_applied → test_verified``: run baseline verify (scoped to
  ``affected_surfaces``), run the attestation's ``rehearsal_commands``
  against the validation surface, run the module's optional
  ``invariants(conn)`` hook.
* ``test_verified → rehearsed``: capture ``source_fingerprint`` of the
  authoritative DB and stamp ``rehearsed_at``.

**What a work item owes is rehearsal, not application.**  The engineer
reviews the rehearsal outcomes and the attestation's
``residual_risk_notes``; the rehearsal receipt is what the evidence gate
reads.  Rehearsal takes the per-model ``LIVE_DB_MIGRATION:<model_name>``
lease and holds it, so a second work item cannot enter migration
territory while one is in flight.

**Applying belongs to the boot converge**
(:mod:`yoke_core.domain.migration_boot_apply`).  A container starting on
new code brings its own database up to that code before it serves, so
"deployed" and "migrated" stop being two things that can disagree.  The
converge computes ``history - ledger``, takes an exclusive per-database
advisory lock, and commits each entry with its ledger row in one
transaction.  There is no operator apply step and no deploy stage that
carries one — an apply that could run ahead of the code is the ordering
failure the boot-coupled design removes.

**Failures** preserve artifacts and surface structured errors:

* Rehearsal failures mark the audit row with
  ``test_copy_failed`` / ``test_apply_failed`` / ``test_verify_failed``.
  The validation DB stays in place for inspection.
* Boot-apply failures mark the audit row with
  ``backup_failed`` / ``live_apply_failed`` / ``live_verify_failed`` and
  fail the boot, because serving behind your own schema is the failure
  the converge exists to prevent.  The rollback backup (when created) is
  preserved so the operator can restore.

The single-unit harness used by the explicit exception pathway stays in
:mod:`yoke_core.domain.migration_harness`.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_core.domain.migration_apply_contract import (
    STATE_PLANNED, STATE_TEST_COPY_CREATED, STATE_TEST_APPLIED,
    STATE_TEST_VERIFIED, STATE_REHEARSED, STATE_BACKUP_CREATED,
    STATE_LIVE_APPLIED, STATE_LIVE_VERIFIED, STATE_COMPLETED,
    FAIL_TEST_COPY, FAIL_TEST_APPLY, FAIL_TEST_VERIFY, FAIL_BACKUP,
    FAIL_LIVE_APPLY, FAIL_LIVE_VERIFY, LEASE_KEY_PREFIX,
    MigrationApplyError, ProfileNotApplyError, CompatibilityClassError,
    RehearsalStaleError, RehearsalMissingError, ModuleResolutionError,
    ModuleContractError, ModuleAttemptResult,
    RehearseResult,
)
from yoke_core.domain.migration_apply_format import (
    format_rehearse,
)
from yoke_core.domain.coordination_leases import LeaseHeldError
from yoke_core.domain.migration_apply_rehearse import rehearse
from yoke_contracts.migration_rehearsal_teaching import CONNECTION_READER


def _parse_item_id(raw: str) -> int:
    # PREFIX-N resolves via the project sequence; bare N = internal id.
    from yoke_core.domain.yok_n_parser import parse_item_id

    return parse_item_id(raw, allow_bare_internal=True)


# _resolve_item_worktree_path moved to migration_apply_resolve so both
# the module-override path and the rehearse wrapper can share it without
# circular imports.


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke migration",
        description=(
            "Rehearse a governed DB migration against the model's validation "
            "surface and record the receipt the evidence gate reads. Applying "
            "belongs to the boot converge, which brings a database up to the "
            "code that is about to serve it."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_r = sub.add_parser(
        "rehearse",
        help="Run the rehearsal unit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_r.add_argument("item_id", help="YOK-N or N")

    args = parser.parse_args(argv)
    item_id: Optional[int] = None
    if args.command == "rehearse":
        try:
            item_id = _parse_item_id(args.item_id)
        except ValueError as exc:
            # The ref resolves against the SELECTED connection's universe, so
            # "not found" usually means the wrong universe rather than a typo.
            print(
                f"ERROR: {exc}; rehearsal is item-bound and reads the item "
                "from the selected connection's universe. List the registered "
                f"connections with `{CONNECTION_READER}`, then rerun under "
                "the non-HTTPS one that holds the item: "
                "`yoke --env <name> migration rehearse ITEM`.",
                file=sys.stderr,
            )
            return 1
    try:
        if args.command == "rehearse":
            assert item_id is not None
            result = rehearse(item_id)
            print(format_rehearse(result))
            return 0 if result.all_succeeded else 1
    except (LeaseHeldError, MigrationApplyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1

__all__ = [
    "FAIL_BACKUP",
    "FAIL_LIVE_APPLY",
    "FAIL_LIVE_VERIFY",
    "FAIL_TEST_APPLY",
    "FAIL_TEST_COPY",
    "FAIL_TEST_VERIFY",
    "LEASE_KEY_PREFIX",
    "CompatibilityClassError",
    "MigrationApplyError",
    "ModuleAttemptResult",
    "ModuleContractError",
    "ModuleResolutionError",
    "ProfileNotApplyError",
    "RehearsalMissingError",
    "RehearsalStaleError",
    "RehearseResult",
    "STATE_BACKUP_CREATED",
    "STATE_COMPLETED",
    "STATE_LIVE_APPLIED",
    "STATE_LIVE_VERIFIED",
    "STATE_PLANNED",
    "STATE_REHEARSED",
    "STATE_TEST_APPLIED",
    "STATE_TEST_COPY_CREATED",
    "STATE_TEST_VERIFIED",
    "main",
    "rehearse",
]

if __name__ == "__main__":
    raise SystemExit(main())
