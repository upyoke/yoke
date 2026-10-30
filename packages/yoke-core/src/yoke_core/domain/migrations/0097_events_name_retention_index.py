"""Replace the event-name index with a concurrent retention range index.

The leading event_name column preserves name-only lookups. Drain older serving
builds before cutover so their additive schema cannot recreate the old index.
"""

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.events_retention_index import (
    ensure_retention_index,
    verify_retention_index,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn) -> None:
    ensure_retention_index(conn, remove_obsolete=True)


def invariants(conn) -> None:
    verify_retention_index(conn)
    if conn.execute(
        "SELECT to_regclass('idx_events_event_name')"
    ).fetchone()[0] is not None:
        raise RuntimeError(
            compose_refusal(
                "events_retention_obsolete_index: the single-column name index remains.",
                recovery="drain older serving builds and rerun migration convergence.",
            )
        )
