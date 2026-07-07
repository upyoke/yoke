"""Metadata-application helpers for the event-registry populator pipeline.

Sibling module of :mod:`yoke_core.domain.populate_registry`. Holds the
per-layer helpers that mutate the ``event_registry`` table after discovery
runs. Each helper is fail-open at row granularity: a missing event raises
:class:`LookupError` from the underlying ``cmd_registry_*`` call, which we
swallow and continue, so a single corrupt row never aborts the whole
populator run.

The data tuples consumed by these helpers live in
:mod:`yoke_core.domain.populate_registry_data_curated` and
:mod:`yoke_core.domain.populate_registry_data_authoritative`.

Helpers exported:

- :func:`_ensure_registry_entry`: idempotent insert then UPDATE.
- :func:`_register_curated_events`: idempotent insert for the curated table.
- :func:`_apply_corrective_updates`: corrective metadata + severity-only.
- :func:`_set_owner_service`: narrow ``owner_service`` UPDATE.
- :func:`_ensure_authoritative_metadata`: final metadata pass.
- :func:`_deprecate_retired_events`: mark deprecated events.
- :func:`_retire_events`: mark retired events.
- :func:`_cleanup_test_sourced_entries`: deprecate test-only entries.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from yoke_core.domain import db_backend, events_crud
from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.populate_registry_data_authoritative import (
    AUTHORITATIVE_METADATA,
    DEPRECATE_LIST,
    RETIRE_LIST,
)
from yoke_core.domain.populate_registry_data_curated import (
    CORRECTIVE_UPDATES,
    CURATED_EVENTS,
    SEVERITY_ONLY_UPDATES,
)


def _ensure_registry_entry(
    db_path: Optional[str],
    name: str,
    kind: str,
    event_type: str,
    service: str,
    description: str,
    severity: str,
) -> None:
    """Insert-or-ignore then update so metadata matches the authoritative row."""
    events_crud.cmd_registry_add(
        db_path=db_path,
        name=name,
        kind=kind,
        event_type=event_type,
        service=service,
        description=description,
        severity=severity,
    )
    try:
        events_crud.cmd_registry_update(
            db_path=db_path,
            name=name,
            event_kind=kind,
            event_type=event_type,
            description=description,
            severity=severity,
        )
    except LookupError:
        # Shouldn't happen because we just ensured the row above; treat
        # as non-fatal so a corrupted registry does not abort the run.
        pass


def _register_curated_events(db_path: Optional[str]) -> None:
    """Explicitly register curated events idempotently."""
    for name, kind, event_type, service, desc, severity in CURATED_EVENTS:
        events_crud.cmd_registry_add(
            db_path=db_path,
            name=name,
            kind=kind,
            event_type=event_type,
            service=service,
            description=desc,
            severity=severity,
        )


def _apply_corrective_updates(db_path: Optional[str]) -> None:
    """Run the corrective UPDATEs that override stale auto-inferred metadata."""
    for name, kind, event_type, service, desc, severity in CORRECTIVE_UPDATES:
        try:
            events_crud.cmd_registry_update(
                db_path=db_path,
                name=name,
                event_kind=kind,
                event_type=event_type,
                description=desc,
                severity=severity,
            )
        except LookupError:
            # Event not registered yet — skip silently (the curated table
            # below or a later discovery run will add it).
            continue
        # ``cmd_registry_update`` does not own owner_service updates, and
        # owner_service must follow the corrective service value.
        _set_owner_service(db_path, name, service)

    for severity, names in SEVERITY_ONLY_UPDATES:
        for name in names:
            try:
                events_crud.cmd_registry_update(
                    db_path=db_path,
                    name=name,
                    severity=severity,
                )
            except LookupError:
                continue


def _set_owner_service(db_path: Optional[str], name: str, service: str) -> None:
    """Direct ``owner_service`` update.

    ``cmd_registry_update`` deliberately does not expose ``owner_service``
    via its kwargs surface (keeps service changes behind a rename
    workflow).  Corrective metadata for events like ``ItemStatusChanged``
    does need to rewrite the service name, so this helper issues a narrow
    UPDATE directly against the same connection.  Guarded by a COUNT check
    so a typo cannot create a phantom row.
    """
    conn = connect(db_path)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM event_registry WHERE event_name={p}",
            (name,),
        ).fetchone()
        if not row or row[0] == 0:
            return
        conn.execute(
            f"UPDATE event_registry SET owner_service={p} WHERE event_name={p}",
            (service, name),
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_authoritative_metadata(db_path: Optional[str]) -> None:
    """Apply the authoritative metadata table."""
    for name, kind, event_type, service, severity, description in AUTHORITATIVE_METADATA:
        _ensure_registry_entry(
            db_path=db_path,
            name=name,
            kind=kind,
            event_type=event_type,
            service=service,
            description=description,
            severity=severity,
        )
        # ensure_registry_entry through cmd_registry_update doesn't touch
        # owner_service — patch it explicitly so the authoritative service
        # name sticks even when the row was previously auto-discovered.
        _set_owner_service(db_path, name, service)


def _deprecate_retired_events(db_path: Optional[str]) -> None:
    for name in DEPRECATE_LIST:
        try:
            events_crud.cmd_registry_deprecate(db_path=db_path, name=name)
        except LookupError:
            continue


def _retire_events(db_path: Optional[str]) -> None:
    for name in RETIRE_LIST:
        try:
            events_crud.cmd_registry_update(
                db_path=db_path,
                name=name,
                status="retired",
            )
        except LookupError:
            continue


def _cleanup_test_sourced_entries(
    db_path: Optional[str], discovered: Sequence[Tuple[str, str]]
) -> None:
    """Deprecate entries whose description points at a test file and that
    have no non-test discovery source.

    Mirrors the cleanup in the original shell script: pure test
    artifacts (where the only call site is under ``/tests/``) get
    deprecated so the registry accurately reflects runtime state.

    Queries the DB directly rather than parsing the pipe-delimited
    ``cmd_registry_list`` output — a description field containing a
    literal ``|`` would otherwise misalign the status column.
    """
    # Build the set of events that have at least one non-test producer.
    prod_names = {name for name, path in discovered if "/tests/" not in path}

    conn = connect(db_path)
    try:
        # deliberate case-sensitive match against internal test-path literal
        rows = query_rows(
            conn,
            "SELECT event_name, COALESCE(description,''), status "
            "FROM event_registry "
            "WHERE status <> 'deprecated' "
            "  AND description LIKE '%%tests/test-%%'",
        )
    finally:
        conn.close()

    for row in rows:
        name = row[0]
        if name in prod_names:
            continue
        try:
            events_crud.cmd_registry_deprecate(db_path=db_path, name=name)
        except LookupError:
            continue
