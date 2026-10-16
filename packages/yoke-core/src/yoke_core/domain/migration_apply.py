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
lease and holds it until the item's merge lands, so a second work item
cannot enter migration territory while one is in flight.

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
import os
import sys
from pathlib import Path
from typing import List, Optional

from yoke_contracts.session_identity import AMBIENT_RESOLUTION_FAILED
from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.domain import db_helpers, db_backend
from yoke_core.domain.session_claimed_worktrees import claimed_worktrees
from yoke_core.domain.migration_apply_contract import (
    STATE_PLANNED,
    STATE_TEST_COPY_CREATED,
    STATE_TEST_APPLIED,
    STATE_TEST_VERIFIED,
    STATE_REHEARSED,
    STATE_BACKUP_CREATED,
    STATE_LIVE_APPLIED,
    STATE_LIVE_VERIFIED,
    STATE_COMPLETED,
    FAIL_TEST_COPY,
    FAIL_TEST_APPLY,
    FAIL_TEST_VERIFY,
    FAIL_BACKUP,
    FAIL_LIVE_APPLY,
    FAIL_LIVE_VERIFY,
    MigrationApplyError,
    ProfileNotApplyError,
    CompatibilityClassError,
    RehearsalStaleError,
    RehearsalMissingError,
    ModuleResolutionError,
    ModuleContractError,
    ModuleAttemptResult,
    RehearseResult,
)
from yoke_core.domain.migration_apply_format import (
    format_rehearse,
)
from yoke_core.domain.coordination_claims import CoordinationClaimHeldError
from yoke_core.domain.migration_apply_rehearse import rehearse
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_contracts.migration_rehearsal_teaching import CONNECTION_READER


def _parse_item_argument(raw: str) -> int:
    # PREFIX-N carries the project prefix and public sequence.
    from yoke_core.domain.yok_n_parser import parse_item_argument

    return parse_item_argument(raw)


def _source_worktree_path(item_id: int, session_id: str) -> Optional[Path]:
    """Revalidate the source runner's binding against item/task lane authority."""
    raw = os.environ.get(SOURCE_DEV_RUN_ROOT_ENV)
    if raw is None:
        return None
    root = Path(raw)
    reason = "source root must name an existing absolute lane directory"
    if raw.strip() and root.is_absolute() and root.is_dir():
        root = root.resolve()
        with db_helpers.connect() as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            lanes = conn.execute(
                "SELECT path FROM item_worktrees "
                f"WHERE item_id = {p} AND state = 'active' "
                "AND released_at IS NULL",
                (item_id,),
            ).fetchall()
            registered = any(row[0] and Path(row[0]).resolve() == root for row in lanes)
            reason = "source root is not an active registered lane of this item"
            if registered:
                if any(
                    lane.item_id == item_id
                    and Path(lane.worktree_path).resolve() == root
                    for lane in claimed_worktrees(conn, session_id=session_id)
                ):
                    return root
                reason = (
                    "caller has no matching active item/task work claim for this lane"
                )
    raise MigrationApplyError(
        f"rehearsal_source_lane_invalid: item_id={item_id}, source={root}: {reason}. "
        "Recovery: inspect `yoke claims work holder-list --session-id-filter "
        f"{session_id}` and the named item's registered lanes; acquire the "
        "matching item/task claim and rerun "
        "`yoke --env <name> dev run --lane <registered-path> -- "
        "yoke migration rehearse ITEM`. Restore a missing lane through its "
        "worktree preparation command; do not set the source binding by hand."
    )


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
            item_id = _parse_item_argument(args.item_id)
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
            session_id = resolve_ambient_session_id()
            if not session_id:
                raise MigrationApplyError(AMBIENT_RESOLUTION_FAILED)
            worktree_path = _source_worktree_path(item_id, session_id)
            if worktree_path is None:
                result = rehearse(item_id, session_id=session_id)
            else:
                result = rehearse(
                    item_id, session_id=session_id, worktree_path=worktree_path
                )
            print(format_rehearse(result))
            return 0 if result.all_succeeded else 1
    except (CoordinationClaimHeldError, MigrationApplyError) as exc:
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
