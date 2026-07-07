"""Actor-grants operator CLI, on real Postgres.

The grant CLI mutates the authority tables (``actor_org_roles`` /
``actor_project_roles``), so it is proven against a disposable real-Postgres
database. ``test_db`` repoints ``YOKE_PG_DSN`` at that database, so the CLI's
own ``db_helpers.connect()`` lands there — no connection monkeypatch needed.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import actor_grants_cli
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.org_schema import org_id_by_slug, seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


@pytest.fixture()
def grantdb(test_db):
    """Disposable Postgres DB with projects, catalog, and default org seeded;
    yields ``(conn, actor_id)``."""
    conn = test_db
    seed_project_identities(conn)
    seed_roles_and_permissions(conn)
    seed_default_org(conn)
    actor_id = seed_human_actor(conn)
    conn.commit()
    return conn, actor_id


def test_grant_org_rejects_project_role(grantdb):
    _, actor_id = grantdb
    rc = actor_grants_cli.main(
        ["grant-org", "--actor", str(actor_id), "--org", "default", "--role", "owner"]
    )
    assert rc == 2


def test_grant_project_rejects_org_role(grantdb):
    _, actor_id = grantdb
    rc = actor_grants_cli.main(
        ["grant-project", "--actor", str(actor_id), "--project", "yoke",
         "--role", "admin"]
    )
    assert rc == 2


def test_grant_org_happy_path(grantdb, capsys):
    conn, actor_id = grantdb
    rc = actor_grants_cli.main(
        ["grant-org", "--actor", str(actor_id), "--org", "default", "--role", "admin"]
    )
    assert rc == 0
    org_id = org_id_by_slug(conn, "default")
    granted = conn.execute(
        "SELECT 1 FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s AND aor.org_id = %s AND r.name = 'admin'",
        (actor_id, org_id),
    ).fetchone()
    assert granted is not None


def test_grant_project_and_list(grantdb, capsys):
    _, actor_id = grantdb
    assert (
        actor_grants_cli.main(
            ["grant-project", "--actor", str(actor_id), "--project", "yoke",
             "--role", "owner"]
        )
        == 0
    )
    capsys.readouterr()
    assert actor_grants_cli.main(["list", "--actor", str(actor_id)]) == 0
    out = capsys.readouterr().out
    assert "project/yoke: owner" in out


def test_grant_unknown_actor_errors(grantdb):
    rc = actor_grants_cli.main(
        ["grant-org", "--actor", "9999", "--org", "default", "--role", "admin"]
    )
    assert rc == 1
