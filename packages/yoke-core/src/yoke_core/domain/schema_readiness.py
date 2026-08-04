"""Read-only probes that the connected DB is fit for the code in front of it.

An HTTP-live core can still be schema-incomplete: the service answers
``/v1/health`` with 200 while a required table is missing and every route
that touches it fails at first query. The health payload's ``schema_ready``
field derives from this module so deploy gates assert schema readiness,
not just liveness.

Two independent questions live here, and a database can pass one while
failing the other. :func:`missing_readiness_tables` asks whether the shapes
this code needs exist; :func:`pending_migration_names` asks whether the
changes this code requires have actually run. The health payload's
``migrations_current`` field derives from the second, which is what lets a
deploy gate distinguish "the container came up" from "the container's
database is the one its code was written against".

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

from typing import Any, List, Sequence, Tuple

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


def pending_migration_names(conn: Any) -> List[str]:
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
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_boot_apply import pending_entries
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    history = ordered_entries(history_dir(migration_history_package))
    if not history:
        return []
    try:
        return [entry.name for entry in pending_entries(conn, history)]
    except Exception:  # noqa: BLE001 — cannot tell reads as not current
        return [entry.name for entry in history]
