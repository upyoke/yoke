"""Read-only probes that the connected DB is fit for the code in front of it.

An HTTP-live core can still be schema-incomplete: the service answers
``/v1/health`` with 200 while a required table is missing and every route
that touches it fails at first query. The health payload's ``schema_ready``
field derives from this module so deploy gates assert schema readiness,
not just liveness.

Three independent questions live here, and a database can pass any of them
while failing another. :func:`missing_readiness_tables` asks whether the
shapes this code needs exist; :func:`pending_migration_names` asks whether
the changes this code requires have actually run. The health payload's
``migrations_current`` field derives from the second, which is what lets a
deploy gate distinguish "the container came up" from "the container's
database is the one its code was written against".

:func:`stranded_by_applied_migrations` asks the question the first two
cannot: *has this database had something applied that this code cannot
survive?* Membership is by name, so an older build whose history simply
does not contain a newer destructive entry computes an empty pending set
and reports itself current — correctly, by its own lights, and fatally.
That build reads columns that are gone. Preserving membership-by-name is
deliberate and must not change: head equality would brick the rollback
direction, which is worse. So the answer comes from the ledger row itself,
which records the floor at apply time precisely because the build in danger
does not ship the entry that would tell it so.

``READINESS_TABLES`` is deliberately small — one representative table per
schema-creation step in :func:`yoke_core.domain.schema_init.converge_core_schema`
(the sequence server boot converges via
:func:`yoke_core.api.server_entrypoint.ensure_core_schema`; ``cmd_init`` layers
seeds and the birth-only tail on top), not the full expected-schema declaration
the schema-drift doctor diffs —
so the probe stays a single cheap ``information_schema`` membership query
on a hot, unauthenticated endpoint. Names must stay clear of the
sensitive-token scan in
:mod:`yoke_core.tools.verify_env_auth_boundary` (no ``token``/``secret``/
``dsn``/``password`` substrings), since missing tables are echoed in the
public health payload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Sequence, Tuple

if TYPE_CHECKING:
    from yoke_core.domain.migration_content_identity import ContentIdentityStatus
    from yoke_core.domain.migration_ledger_contract import LedgerContract

READINESS_TABLES: Tuple[str, ...] = (
    "items",
    "projects",
    "events",
    "harness_sessions",
    "roles",
    "strategy_docs",
    # representative of the external-identity step
    # (create_external_identity_tables): a deploy that converges the schema
    # on boot must land it before reporting schema_ready.
    "actor_external_identities",
    # representative of the UI-preference step (create_ui_preference_tables):
    # the Overview activation read latches into overview_activation_facts on
    # first dispatch, so a booted core must carry the step before it is ready.
    "actor_ui_preferences",
)


def missing_readiness_tables(
    conn: Any, tables: Sequence[str] = READINESS_TABLES
) -> List[str]:
    """Return the subset of *tables* absent from the connected database."""
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(tables),),
    )
    present = set()
    for row in cur.fetchall():
        present.add(row["table_name"] if isinstance(row, dict) else row[0])
    return [table for table in tables if table not in present]


def pending_migration_names(
    conn: Any,
    history: Sequence[Any],
    ledger: LedgerContract,
) -> List[str]:
    """Return the history entries this database has not applied.

    Complements :func:`missing_readiness_tables`: that answers "does the
    database have the shapes this code needs?", this answers "has it run the
    changes this code requires?". A container can pass the first and fail the
    second — every table present, but a rewrite the code depends on never
    applied — which is the divergence class the ordered history exists to make
    visible instead of silent.

    An unreadable ledger reports the whole history as pending rather than
    raising: at this altitude "cannot tell" and "not current" must be the same
    answer, because a health gate that fails open on a broken probe is worse
    than one that reports not-ready.
    """
    from yoke_core.domain.migration_ledger_contract import pending_entries

    if not history:
        return []
    try:
        rows = conn.execute(
            f"SELECT {ledger.entry_column} FROM {ledger.table}"
        ).fetchall()
        applied = [str(row[0]) for row in rows]
        return pending_entries([entry.name for entry in history], applied)
    except Exception:  # noqa: BLE001 — cannot tell reads as not current
        return [entry.name for entry in history]


def migration_content_identity_status(
    conn: Any,
    history: Sequence[Any],
    ledger: LedgerContract,
) -> ContentIdentityStatus:
    """Return verified, adoption-required, and mismatched ledger evidence.

    This is deliberately separate from :func:`pending_migration_names`.
    Legacy NULL digests require an explicit artifact-bound adoption, but do
    not make an otherwise current database unservable in this rollout.  A
    non-NULL mismatch is fatal to boot apply and is exposed here for health,
    fleet, and doctor readers that do not execute the applier.
    """
    from yoke_core.domain.migration_content_identity import (
        read_content_identity_status,
    )

    return read_content_identity_status(conn, history, ledger)


def stranded_by_applied_migrations(
    conn: Any,
    running_version: str,
    history: Sequence[Any],
    ledger: LedgerContract,
) -> List[str]:
    """Return one finding per applied entry this build is too old to serve.

    Reads the floor recorded on each ledger row rather than the entry module,
    because a build old enough to be stranded does not ship the entry that
    stranded it. Each finding names the entry, the floor, the running
    version, and the way out, since this text is what an operator sees when
    a container refuses to go healthy.

    ``history`` is the permanent history shipped by the running artifact. It
    distinguishes a known compatible entry whose declaration intentionally has
    no floor from an entry the running artifact does not contain. An unknown
    entry without a recorded floor is not provably safe and therefore refuses
    service. A known entry whose declared floor is absent or disagrees with its
    ledger row also refuses rather than trusting incomplete evidence.

    An unresolved running version is safe only for entries present in
    ``history``: a source checkout that contains an entry necessarily contains
    the code shipped with that entry. It cannot make the same claim about an
    unknown applied entry, so that comparison fails closed.

    An unreadable ledger is itself a finding. The pending probe independently
    reports the history as pending, but ``can_serve_this_database`` must remain
    truthful when consumed on its own rather than relying on every caller to
    compose both fields correctly.
    """
    from yoke_core.domain.migration_history import load_migration_module
    from yoke_core.domain.migration_serving_version import (
        ServingVersionError,
        declared_minimum,
        satisfies_minimum,
        version_is_unresolved,
    )

    try:
        rows = conn.execute(
            f"SELECT {ledger.entry_column}, {ledger.serving_floor_column} "
            f"FROM {ledger.table}"
        ).fetchall()
    except Exception:  # noqa: BLE001 — public health must not expose DB details
        return [
            f"{ledger.table}: migration ledger is unreadable, so serving "
            "compatibility cannot be proven; repair the ledger before serving"
        ]

    known = {entry.name: entry for entry in history}
    unresolved = version_is_unresolved(running_version)
    findings: List[str] = []
    for row in rows:
        name = str(
            row[ledger.entry_column] if isinstance(row, dict) else row[0]
        )
        raw_floor = (
            row[ledger.serving_floor_column] if isinstance(row, dict) else row[1]
        )
        floor = str(raw_floor).strip() if raw_floor is not None else ""
        entry = known.get(name)
        declared = None
        if entry is not None:
            try:
                declared = declared_minimum(
                    load_migration_module(entry.path, entry.name)
                )
            except Exception:  # noqa: BLE001 — unreadable declaration is unsafe
                findings.append(
                    f"{name}: packaged serving-floor declaration is unreadable; "
                    "repair the migration history before serving"
                )
                continue

        if not floor:
            if entry is None:
                findings.append(
                    f"{name}: applied entry is absent from this build's history "
                    "and has no recorded minimum serving version; deploy a build "
                    "that contains the entry or repair its ledger evidence"
                )
            elif declared is not None:
                findings.append(
                    f"{name}: declared minimum serving version {declared} is "
                    "absent from its applied ledger row; backfill the floor before "
                    "serving"
                )
            continue

        if declared is not None and floor != declared:
            findings.append(
                f"{name}: recorded minimum serving version {floor!r} does not "
                f"match packaged declaration {declared!r}; repair the ledger "
                "before serving"
            )
            continue

        if unresolved:
            if entry is None:
                findings.append(
                    f"{name}: requires engine {floor} or newer, but this build's "
                    "engine version is unresolved and the entry is absent from "
                    "its history; deploy an identified compatible build"
                )
            continue
        try:
            if satisfies_minimum(running_version, str(floor)):
                continue
        except ServingVersionError:
            # A malformed floor cannot prove compatibility. Keep the public
            # finding free of database internals while refusing service.
            findings.append(
                f"{name}: recorded minimum serving version {floor!r} is not a "
                "valid version; this database's ledger needs repair"
            )
            continue
        findings.append(
            f"{name}: applied to this database, which requires engine {floor} "
            f"or newer to serve against it, but this build is "
            f"{running_version}. It reads surfaces that entry removed. Deploy "
            f"{floor} or newer; rolling further back does not restore them."
        )
    return findings
