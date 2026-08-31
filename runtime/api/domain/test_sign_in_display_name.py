"""The sign-in ladder adopts the provider's name as the actor display label."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.actor_labels import (
    DISPLAY_LABEL_SURFACE,
    GITHUB_LABEL_SURFACE,
)
from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor, set_actor_label
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identities import link_external_identity
from yoke_core.domain.external_identity_schema import (
    create_external_identity_tables,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.sign_in_resolution import (
    OUTCOME_LINKED_IDENTITY,
    resolve_sign_in,
)


_ISSUER = "https://issuer.example"


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        create_auth_tables(c)
        create_external_identity_tables(c)
        seed_roles_and_permissions(c)
        seed_default_org(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def _claims(**overrides: Any) -> dict:
    base = {
        "issuer": _ISSUER,
        "subject": "sub-1",
        "email": "casey@example.com",
        "email_verified": True,
        "name": "Casey Nguyen",
    }
    base.update(overrides)
    return base


def _linked_member(conn, *, subject: str, handle: str) -> int:
    """A member whose identity is already linked, as a synced membership is."""
    actor_id = seed_human_actor(conn)
    set_actor_label(conn, actor_id, handle, surface=GITHUB_LABEL_SURFACE)
    link_external_identity(
        conn, actor_id=actor_id, issuer=_ISSUER, subject=subject,
    )
    return actor_id


def _display_rows(conn, actor_id: int) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT label FROM actor_labels WHERE actor_id = %s AND surface = %s",
            (actor_id, DISPLAY_LABEL_SURFACE),
        ).fetchall()
    ]


def test_sync_writes_the_display_row_for_a_linked_member(conn):
    actor_id = _linked_member(conn, subject="sub-1", handle="casey")
    assert actor_display_name(conn, actor_id) == "casey"

    result = resolve_sign_in(conn, _claims())

    assert result.outcome == OUTCOME_LINKED_IDENTITY
    assert result.actor_id == actor_id
    assert actor_display_name(conn, actor_id) == "Casey Nguyen"


def test_a_renamed_account_propagates_on_the_next_sync(conn):
    actor_id = _linked_member(conn, subject="sub-1", handle="casey")
    resolve_sign_in(conn, _claims())

    resolve_sign_in(conn, _claims(name="Casey Rivera"))

    assert _display_rows(conn, actor_id) == ["Casey Rivera"]


def test_an_account_with_no_name_leaves_the_fallback_chain_untouched(conn):
    actor_id = _linked_member(conn, subject="sub-1", handle="casey")

    for absent in (None, "", "   "):
        assert resolve_sign_in(conn, _claims(name=absent)).succeeded
        assert _display_rows(conn, actor_id) == []
        assert actor_display_name(conn, actor_id) == "casey"


def test_a_later_nameless_sync_keeps_the_name_an_earlier_one_adopted(conn):
    actor_id = _linked_member(conn, subject="sub-1", handle="casey")
    resolve_sign_in(conn, _claims())

    resolve_sign_in(conn, _claims(name=None))

    assert _display_rows(conn, actor_id) == ["Casey Nguyen"]


def test_each_member_of_an_org_owns_only_its_own_display_row(conn):
    first = _linked_member(conn, subject="sub-1", handle="casey")
    second = _linked_member(conn, subject="sub-2", handle="dana")

    resolve_sign_in(conn, _claims())

    assert _display_rows(conn, first) == ["Casey Nguyen"]
    assert _display_rows(conn, second) == []
    assert actor_display_name(conn, second) == "dana"

    resolve_sign_in(
        conn, _claims(subject="sub-2", email="dana@example.com", name="Dana Ito"),
    )

    assert _display_rows(conn, first) == ["Casey Nguyen"]
    assert _display_rows(conn, second) == ["Dana Ito"]


def test_two_members_sharing_a_name_both_keep_it(conn):
    first = _linked_member(conn, subject="sub-1", handle="casey")
    second = _linked_member(conn, subject="sub-2", handle="dana")

    resolve_sign_in(conn, _claims())
    resolve_sign_in(
        conn,
        _claims(subject="sub-2", email="dana@example.com", name="Casey Nguyen"),
    )

    assert _display_rows(conn, first) == ["Casey Nguyen"]
    assert _display_rows(conn, second) == ["Casey Nguyen"]
