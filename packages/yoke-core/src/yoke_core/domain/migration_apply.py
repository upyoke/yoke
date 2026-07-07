"""Two-unit apply contract for governed DB migrations.

Per the governed-DB-mutation contract, a ticket with
``db_mutation_profile.mutation_intent = "apply"`` inside ``implementing``
runs its migration in two distinct units, separated by a mandatory
operator checkpoint:

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

**Operator checkpoint.**  The engineer reviews the rehearsal outcomes
and the attestation's ``residual_risk_notes``.  The checkpoint is
enforced structurally: rehearse and live-apply are separate CLI
invocations — the two-unit contract cannot execute atomically from a
single function call.

**Live-apply unit** (per-model ``LIVE_DB_MIGRATION:<model_name>`` lease,
rollback backup, authoritative mutation):

* Freshness gate: the latest rehearsed audit row's fingerprint must
  still match the authoritative DB AND ``now - rehearsed_at`` must be
  under 30 minutes (:func:`schema_fingerprint.freshness_expired`).
  Either fails → refuse; no lease acquired; operator re-rehearses.
* Acquire lease.  Held row conflict → :class:`LeaseHeldError` surfaces
  the existing holder.
* ``rehearsed → backup_created``: create a rollback backup.
* ``backup_created → live_applied``: apply the module to the
  authoritative DB.
* ``live_applied → live_verified``: run baseline verify + author
  invariants on the authoritative DB.
* ``live_verified → completed``: mark success; release the lease.

**Failures** preserve artifacts and surface structured errors:

* Rehearsal failures mark the audit row with
  ``test_copy_failed`` / ``test_apply_failed`` / ``test_verify_failed``.
  The validation DB stays in place for inspection; no lease was ever
  acquired.
* Live-apply failures mark the audit row with
  ``backup_failed`` / ``live_apply_failed`` / ``live_verify_failed``.
  The lease is released with a structured ``release_reason``; the
  rollback backup (when created) is preserved so the operator can
  manually restore.  No auto-rollback in MVP.

Retire flow is NOT handled here — see
:mod:`yoke_core.domain.migration_retire_record`.  The single-unit
harness used by the explicit exception pathway stays in
:mod:`yoke_core.domain.migration_harness`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.coordination_leases import LeaseHeldError
from yoke_core.domain.migration_apply_contract import (
    STATE_PLANNED, STATE_TEST_COPY_CREATED, STATE_TEST_APPLIED,
    STATE_TEST_VERIFIED, STATE_REHEARSED, STATE_BACKUP_CREATED,
    STATE_LIVE_APPLIED, STATE_LIVE_VERIFIED, STATE_COMPLETED,
    FAIL_TEST_COPY, FAIL_TEST_APPLY, FAIL_TEST_VERIFY, FAIL_BACKUP,
    FAIL_LIVE_APPLY, FAIL_LIVE_VERIFY, LEASE_KEY_PREFIX,
    MigrationApplyError, ProfileNotApplyError, CompatibilityClassError,
    RehearsalStaleError, RehearsalMissingError, ModuleResolutionError,
    ModuleContractError, ModuleOverrideError, ModuleAttemptResult,
    RehearseResult, LiveApplyResult,
)
from yoke_core.domain.migration_apply_help import SELF_MIGRATION_TEMP_RECIPE
from yoke_core.domain.migration_apply_live import live_apply
from yoke_core.domain.migration_apply_rehearse import rehearse
from yoke_core.domain.migration_apply_resolve import (
    ModuleOverrideResolution, _load_item, _resolve_item_worktree_path,
    _resolve_profile_or_raise, control_conn_db_path, resolve_module_override,
)


def _parse_item_id(raw: str) -> int:
    text = raw.strip()
    if text.upper().startswith("YOK-"):
        text = text[4:]
    return int(text.lstrip("0") or "0")


def _format_override(
    override: Optional[ModuleOverrideResolution],
) -> Optional[str]:
    if override is None:
        return None
    return (
        f"  override_source={override.source_path} "
        f"override_worktree={override.worktree_path}"
    )


def _format_rehearse(
    result: RehearseResult,
    override: Optional[ModuleOverrideResolution] = None,
) -> str:
    lines = [
        f"rehearse YOK-{result.item_id} model={result.model_name} "
        f"validation_db={result.validation_db_path}",
    ]
    extra = _format_override(override)
    if extra is not None:
        lines.append(extra)
    for mod in result.modules:
        lines.append(
            f"  {mod.identifier}: state={mod.state}"
            + (f" ERROR={mod.error}" if mod.error else "")
        )
    if result.source_fingerprint:
        lines.append(
            f"  source_fingerprint={result.source_fingerprint[:16]}... "
            f"rehearsed_at={result.rehearsed_at}"
        )
    return "\n".join(lines)


def _format_live_apply(
    result: LiveApplyResult,
    override: Optional[ModuleOverrideResolution] = None,
) -> str:
    lines = [
        f"live-apply YOK-{result.item_id} model={result.model_name} "
        f"authoritative_db={result.authoritative_db_path} "
        f"lease_id={result.lease_id}",
    ]
    extra = _format_override(override)
    if extra is not None:
        lines.append(extra)
    for mod in result.modules:
        lines.append(
            f"  {mod.identifier}: state={mod.state}"
            + (f" ERROR={mod.error}" if mod.error else "")
        )
    return "\n".join(lines)


def _resolve_override_from_cli(
    item_id: int, requested: Optional[str],
) -> Optional[ModuleOverrideResolution]:
    """Validate the override against the item's worktree + declared modules.

    The CLI reads the live control DB so production callers see the same
    worktree / profile validation that tests cover via direct API. The
    item's worktree path is derived from ``items.worktree`` and this
    machine's checkout mapping — no envelope read.
    """
    if not requested:
        return None
    conn = db_helpers.connect()
    try:
        item = _load_item(conn, item_id)
        profile = _resolve_profile_or_raise(item)
        worktree_path = _resolve_item_worktree_path(conn, item_id)
    finally:
        conn.close()
    return resolve_module_override(
        requested_path=requested,
        item_id=item_id,
        declared_modules=profile["migration_modules"],
        worktree_path=worktree_path,
    )


# _resolve_item_worktree_path moved to migration_apply_resolve so both
# the module-override path and the rehearse/live-apply wrappers can
# share it without circular imports.


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.migration_apply",
        description=(
            "Two-unit governed DB migration apply contract. Separate "
            "'rehearse' and 'live-apply' subcommands enforce the mandatory "
            "operator checkpoint between units."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    _override_help = (
        "Path to a migration module file under the active item worktree "
        "(sanctioned cross-worktree apply contract). The slug must be "
        "declared in db_mutation_profile.migration_modules and the "
        "active session must hold a work-claim on that item."
    )

    p_r = sub.add_parser(
        "rehearse",
        help="Run the rehearsal unit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SELF_MIGRATION_TEMP_RECIPE,
    )
    p_r.add_argument("item_id", help="YOK-N or N")
    p_r.add_argument(
        "--module-path-override", default=None, help=_override_help,
    )

    p_l = sub.add_parser(
        "live-apply",
        help="Run the live-apply unit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SELF_MIGRATION_TEMP_RECIPE,
    )
    p_l.add_argument("item_id", help="YOK-N or N")
    p_l.add_argument(
        "--module-path-override", default=None, help=_override_help,
    )

    args = parser.parse_args(argv)
    item_id = _parse_item_id(args.item_id)

    try:
        override = _resolve_override_from_cli(
            item_id, args.module_path_override,
        )
    except ModuleOverrideError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 4
    except MigrationApplyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    override_worktree = override.worktree_path if override is not None else None
    try:
        if args.command == "rehearse":
            result = rehearse(
                item_id,
                module_override=override,
                worktree_path=override_worktree,
            )
            print(_format_rehearse(result, override=override))
            return 0 if result.all_succeeded else 1
        if args.command == "live-apply":
            try:
                result = live_apply(
                    item_id,
                    module_override=override,
                    worktree_path=override_worktree,
                )
            except RehearsalStaleError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2
            except RehearsalMissingError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2
            except CompatibilityClassError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2
            except ModuleOverrideError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 4
            except LeaseHeldError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 3
            print(_format_live_apply(result, override=override))
            return 0 if result.all_succeeded else 1
    except MigrationApplyError as exc:
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
    "LiveApplyResult",
    "MigrationApplyError",
    "ModuleAttemptResult",
    "ModuleContractError",
    "ModuleOverrideError",
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
    "live_apply",
    "main",
    "rehearse",
]

if __name__ == "__main__":
    raise SystemExit(main())
