"""Live per-project deploy locks are released and their index dropped.

Released deploy-lock rows stay as claim history, and every other claim kind
is left exactly as it was.
"""

from __future__ import annotations

import importlib
import json

import pytest

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    migration_target,
    seed_session,
)
from yoke_core.domain.schema_common import _get_indexes
from yoke_core.domain.work_claim_target_sql import scope_text_sql

migration = importlib.import_module(
    "yoke_core.domain.migrations.0070_release_retired_deploy_locks"
)

HOLDER = "deploy-holder"
EARLIER_RELEASE = "2026-09-01T00:00:00Z"


def _insert_claim(conn, kind: str, scope: str, released_at: str | None) -> int:
    row = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat, released_at, release_reason) "
        "VALUES (%s, %s, %s, 'exclusive', %s, %s, %s, %s) RETURNING id",
        (
            HOLDER,
            kind,
            scope,
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
            released_at,
            "completed" if released_at else None,
        ),
    ).fetchone()
    return int(row[0])


def _deploy_scope(slug: str = "yoke") -> str:
    return json.dumps({"project_id": PROJECT_YOKE, "project_slug": slug})


def _claim(conn, claim_id: int):
    return conn.execute(
        "SELECT released_at, release_reason, release_reason_intent "
        "FROM work_claims WHERE id=%s",
        (claim_id,),
    ).fetchone()


@pytest.fixture
def seeded(test_db):
    seed_session(test_db, HOLDER, PROJECT_YOKE)
    claims = {
        "live_deploy": _insert_claim(
            test_db, migration.RETIRED_KIND, _deploy_scope(), None
        ),
        "released_deploy": _insert_claim(
            test_db, migration.RETIRED_KIND, _deploy_scope(), EARLIER_RELEASE
        ),
        "live_migration": _insert_claim(
            test_db,
            "migration_serialization",
            migration_target(7).scope_json(),
            None,
        ),
    }
    project = scope_text_sql(test_db, "scope", "project_id")
    test_db.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {migration.RETIRED_INDEX} "
        f"ON work_claims(({project})) "
        f"WHERE released_at IS NULL AND target_kind='{migration.RETIRED_KIND}'"
    )
    test_db.commit()
    return test_db, claims


def test_live_deploy_locks_release_and_the_index_drops(seeded) -> None:
    conn, claims = seeded
    with pytest.raises(RuntimeError, match="retired_deploy_lock_live"):
        migration.invariants(conn)

    migration.apply(conn)
    conn.commit()

    released_at, reason, intent = _claim(conn, claims["live_deploy"])
    assert released_at is not None
    assert reason == migration.RELEASE_REASON == "released"
    assert intent == migration.RELEASE_INTENT

    history = _claim(conn, claims["released_deploy"])
    assert tuple(history) == (EARLIER_RELEASE, "completed", None)

    other = _claim(conn, claims["live_migration"])
    assert tuple(other) == (None, None, None)

    assert migration.RETIRED_INDEX not in set(_get_indexes(conn, "work_claims"))
    migration.invariants(conn)


def test_apply_is_idempotent(seeded) -> None:
    conn, claims = seeded
    migration.apply(conn)
    conn.commit()
    first = {name: tuple(_claim(conn, claim_id)) for name, claim_id in claims.items()}

    migration.apply(conn)
    conn.commit()

    again = {name: tuple(_claim(conn, claim_id)) for name, claim_id in claims.items()}
    assert again == first
    migration.invariants(conn)


def test_a_surviving_index_fails_invariants(seeded) -> None:
    conn, claims = seeded
    conn.execute(
        "UPDATE work_claims SET released_at=%s WHERE id=%s",
        (EARLIER_RELEASE, claims["live_deploy"]),
    )
    with pytest.raises(RuntimeError, match="retired_deploy_lock_index"):
        migration.invariants(conn)
