"""Verified destination ownership during an isolated hosted archive restore.

The hosted importer owns the restore authority: it binds the verified person
and staging database to its durable import job before calling this helper.
This is credential establishment for a restored copy, never a normal role
grant. Existing people and owners survive unchanged. Normal grants continue
through actor_role_grants and its owner guard.
"""

from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.actor_state import actor_is_active
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.external_identities import link_external_identity, resolve_external_identity
from yoke_contracts.timestamps import utc_now
from yoke_contracts.refusal_recovery import compose_refusal


def admit_restored_owner(conn, *, issuer: str, subject: str, email: str, name: str) -> int:
    """Establish the job's verified importer after copied credentials retire.

    PostgreSQL staging restores only; caller owns commit. Active human tokens
    or web sessions mean this is not a retired restored copy and refuse before
    any identity or role write. A linked disabled person remains disabled.
    """
    with savepoint(conn, "restored_owner", owns=False):
        orgs = conn.execute("SELECT id FROM organizations ORDER BY id FOR UPDATE").fetchall()
        if len(orgs) != 1:
            raise ValueError(compose_refusal("restore owner admission requires exactly one organization", recovery="Inspect the archive before retrying the isolated restore"))
        live = conn.execute(
            "SELECT 1 FROM api_tokens t JOIN actors a ON a.id=t.actor_id "
            "WHERE a.kind='human' AND t.status='active' LIMIT 1"
        ).fetchone()
        web = conn.execute("SELECT 1 FROM web_sessions WHERE revoked_at IS NULL LIMIT 1").fetchone()
        if live or web:
            raise ValueError(compose_refusal("restore owner admission requires retired human credentials", recovery="Retire copied credentials through archive restore before admitting its destination owner"))
        actor = resolve_external_identity(conn, issuer=issuer, subject=subject)
        if actor is None:
            actor = seed_human_actor(conn, name or email, commit=False)
        kind = conn.execute("SELECT kind FROM actors WHERE id=%s", (actor,)).fetchone()
        if kind is None or kind[0] != "human":
            raise ValueError(compose_refusal("restore owner admission requires a human identity", recovery="Link the importing sign-in to a human in the source archive, then export again"))
        if not actor_is_active(conn, actor):
            raise ValueError(compose_refusal("actor_disabled: the importing person is disabled", recovery="Enable the importing person before exporting a new archive"))
        link_external_identity(conn, actor_id=actor, issuer=issuer, subject=subject,
                               email=email, created_by_actor_id=actor, commit=False)
        conn.execute("DELETE FROM actor_org_roles WHERE actor_id=%s AND org_id=%s", (actor, orgs[0][0]))
        conn.execute(
            "INSERT INTO actor_org_roles (actor_id,org_id,role_id,granted_at,granted_by_actor_id) "
            "SELECT %s,%s,id,%s,%s FROM roles WHERE name='owner'",
            (actor, orgs[0][0], instant_parameter(conn, utc_now()), actor),
        )
    return actor
