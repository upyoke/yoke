"""The machine owner's org admin grant, at birth and after an upgrade.

A universe born by an engine that predates the grant keeps running after
that engine is upgraded in place, and nothing on the upgrade path
re-enters birth. The observed shape was a bound session denied on every
mutation with a message that named a permission and no way to get it, so
these tests pin all three surfaces that now close it: birth grants,
session registration converges the grant an upgrade left missing, and a
denial caused by that missing grant names the command that writes it.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import local_universe as lu
from yoke_core.domain.actor_permissions import PermissionDenied, require_permission
from yoke_core.domain.local_operating_actor import (
    OPERATING_ACTOR_GRANT_REPAIR,
    converge_operating_actor_grant,
    ensure_local_operating_actor,
    grant_tables_present,
    holds_org_admin,
    missing_grant_repair_detail,
    single_owner_universe,
)


def _human_actor_id(conn) -> int:
    return int(
        conn.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


def _revoke_grant(conn) -> int:
    """Model a universe born before the grant existed."""
    actor_id = _human_actor_id(conn)
    conn.execute("DELETE FROM actor_org_roles WHERE actor_id = %s", (actor_id,))
    conn.commit()
    assert not holds_org_admin(conn, actor_id)
    return actor_id


def _project_id(conn) -> int:
    """A project owned by the universe's own org, as a born universe has."""
    from yoke_core.domain.org_schema import seed_default_org

    org_id = seed_default_org(conn)
    row = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
    if row is None:
        row = conn.execute(
            "INSERT INTO projects (org_id, slug, name, github_repo, "
            "default_branch, public_item_prefix, created_at) VALUES "
            "(%s, 'yoke', 'Yoke', '', 'main', 'YOK', '2026-05-01T00:00:00Z') "
            "RETURNING id",
            (org_id,),
        ).fetchone()
    else:
        conn.execute(
            "UPDATE projects SET org_id = %s WHERE id = %s", (org_id, int(row[0]))
        )
    conn.commit()
    return int(row[0])


def test_birth_leaves_the_operating_actor_holding_org_admin(test_db):
    """The birth path's own grant: the actor exists AND carries authority."""
    actor_id = lu._ensure_human_actor(lambda _line: None)

    assert holds_org_admin(test_db, actor_id)


def test_birth_grant_is_idempotent_on_a_universe_that_already_has_it(test_db):
    ensure_local_operating_actor(test_db)
    actor_id, seeded = ensure_local_operating_actor(test_db)

    assert seeded is False
    grants = test_db.execute(
        "SELECT COUNT(*) FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s AND r.name = 'admin'",
        (actor_id,),
    ).fetchone()[0]
    assert int(grants) == 1


def test_upgrade_converges_a_grant_less_universe(test_db):
    actor_id = _revoke_grant(test_db)

    assert converge_operating_actor_grant(test_db) == actor_id
    assert holds_org_admin(test_db, actor_id)


def test_upgrade_convergence_writes_nothing_once_the_grant_exists(test_db):
    ensure_local_operating_actor(test_db)

    assert converge_operating_actor_grant(test_db) is None


def test_upgrade_convergence_skips_a_universe_with_several_people(test_db):
    """A multi-tenant control plane never hands org admin to a stranger."""
    _revoke_grant(test_db)
    test_db.execute(
        "INSERT INTO actors (kind, created_at) VALUES ('human', '2026-05-01T00:00:00Z')"
    )
    test_db.commit()

    assert single_owner_universe(test_db) is None
    assert converge_operating_actor_grant(test_db) is None
    granted = test_db.execute("SELECT COUNT(*) FROM actor_org_roles").fetchone()[0]
    assert int(granted) == 0


def test_denial_names_the_repair_when_the_grant_is_absent(test_db):
    actor_id = _revoke_grant(test_db)
    project_id = _project_id(test_db)

    with pytest.raises(PermissionDenied) as denial:
        require_permission(
            test_db,
            actor_id=actor_id,
            project_id=project_id,
            permission_key="items.write",
        )

    assert OPERATING_ACTOR_GRANT_REPAIR in str(denial.value)


def test_a_denial_with_the_grant_present_stays_an_authorization_answer(test_db):
    """Naming a local repair on a real permission refusal would mislead."""
    ensure_local_operating_actor(test_db)
    actor_id = _human_actor_id(test_db)

    assert missing_grant_repair_detail(test_db, actor_id) == ""


def test_convergence_leaves_a_grant_less_schema_and_its_caller_untouched(test_db):
    """A database without the grant tables must cost the caller nothing.

    Both readers run inside somebody else's open transaction. Probing a
    missing table would abort it, and rolling back to recover would
    discard the caller's own uncommitted rows — which is exactly what
    happened to a suite whose minimal schema carries actors but no
    org/role tables: its freshly inserted items and sessions vanished.
    """
    test_db.execute("DROP TABLE IF EXISTS actor_org_roles CASCADE")
    test_db.commit()
    assert grant_tables_present(test_db) is False

    test_db.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        "VALUES ('system', 'grant-witness', '2026-05-01T00:00:00Z')"
    )
    uncommitted = int(test_db.execute("SELECT COUNT(*) FROM actors").fetchone()[0])

    assert converge_operating_actor_grant(test_db) is None
    assert missing_grant_repair_detail(test_db, 1) == ""

    still_there = int(test_db.execute("SELECT COUNT(*) FROM actors").fetchone()[0])
    assert still_there == uncommitted
