"""Release every live per-project deploy lock and drop its exclusivity index.

Deployment runs no longer require a ``deploy_serialization`` claim: a run
occupies the servers it deploys to until its QA settles, and its live
driver attachment says who drives it. A hold still live when this ships
would never be released by anything — the kind is sticky, so no sweep
reclaims it — and would keep rendering as a lock nobody needs.

The rows themselves are retained: a released claim is history, and the
target-kind CHECK keeps admitting the kind so that history stays valid.
Only the live holds are closed and the index that made them exclusive is
dropped.

Self-contained, as a history entry must be: the kind and index names are
written here rather than imported from modules that no longer carry them.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _get_indexes, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
#: The entry that created the exclusivity index asserted it exists; the
#: index is dropped here, so that claim no longer stands.
RETIRES_INVARIANTS = ("0036_deploy_serialization_work_claim_kind",)
CLAIM_TABLE = "work_claims"
RETIRED_KIND = "deploy_serialization"
RETIRED_INDEX = "idx_work_claims_active_deploy_serialization"
RELEASE_REASON = "released"
RELEASE_INTENT = "deploy lock retired: runs serialize by target occupancy"


def apply(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    marker = "%s" if connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE {CLAIM_TABLE} SET released_at={marker}, "
        f"release_reason={marker}, release_reason_intent={marker} "
        f"WHERE target_kind={marker} AND released_at IS NULL",
        (iso8601_now(), RELEASE_REASON, RELEASE_INTENT, RETIRED_KIND),
    )
    conn.execute(f"DROP INDEX IF EXISTS {RETIRED_INDEX}")


def invariants(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    marker = "%s" if connection_is_postgres(conn) else "?"
    if conn.execute(
        f"SELECT 1 FROM {CLAIM_TABLE} WHERE target_kind={marker} "
        "AND released_at IS NULL LIMIT 1",
        (RETIRED_KIND,),
    ).fetchone():
        raise RuntimeError(
            "retired_deploy_lock_live: a deploy_serialization claim is still "
            "live. Recovery: rehearse this entry and boot the candidate before "
            "serving."
        )
    if RETIRED_INDEX in set(_get_indexes(conn, CLAIM_TABLE)):
        raise RuntimeError(
            f"retired_deploy_lock_index: {RETIRED_INDEX} still exists. "
            "Recovery: rehearse this entry and boot the candidate before serving."
        )
