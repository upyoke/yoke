"""API-token operator CLI coverage."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import api_tokens_cli
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import TOKEN_PREFIX, verify_token
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


@pytest.fixture()
def tokendb(test_db):
    conn = test_db
    seed_project_identities(conn)
    seed_roles_and_permissions(conn)
    conn.commit()
    return conn


def test_bootstrap_admin_outputs_raw_token_once_and_stores_only_hash(tokendb, capsys):
    rc = api_tokens_cli.main(
        ["bootstrap-admin", "--actor-label", "ops-lead", "--project", "yoke"]
    )
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    assert body["raw_token"].startswith(TOKEN_PREFIX)

    verified = verify_token(tokendb, body["raw_token"])
    assert verified.actor_id == body["actor_id"]
    project_id = resolve_project_id(tokendb, "yoke")
    row = tokendb.execute(
        "SELECT 1 FROM actor_project_roles "
        "WHERE actor_id = %s AND project_id = %s",
        (body["actor_id"], project_id),
    ).fetchone()
    assert row is not None
    raw_stored = tokendb.execute(
        "SELECT 1 FROM api_tokens WHERE token_hash = %s",
        (body["raw_token"],),
    ).fetchone()
    assert raw_stored is None


def test_bootstrap_admin_defaults_to_neutral_label_and_org_admin(tokendb, capsys):
    """No flags: the admin label is neutral and the grant is the org admin role."""
    from yoke_core.domain.actors import resolve_actor_by_label
    from yoke_core.domain.api_tokens import DEFAULT_ADMIN_ACTOR_LABEL

    rc = api_tokens_cli.main(["bootstrap-admin"])
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    assert resolve_actor_by_label(tokendb, DEFAULT_ADMIN_ACTOR_LABEL) == body["actor_id"]
    row = tokendb.execute(
        "SELECT 1 FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s AND r.name = 'admin'",
        (body["actor_id"],),
    ).fetchone()
    assert row is not None


def test_mint_and_revoke(tokendb, capsys):
    actor_id = seed_human_actor(tokendb)
    rc = api_tokens_cli.main(
        ["mint", "--actor", str(actor_id), "--name", "dev-machine"]
    )
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    verify_token(tokendb, body["raw_token"])

    assert api_tokens_cli.main(["revoke", "--token-id", str(body["token_id"])]) == 0
    with pytest.raises(Exception):
        verify_token(tokendb, body["raw_token"])


def test_mint_unknown_actor_errors(tokendb):
    rc = api_tokens_cli.main(["mint", "--actor", "9999", "--name", "ghost"])
    assert rc == 1
