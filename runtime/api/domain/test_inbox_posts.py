"""Durable audience-addressed work has one shared completion state."""

from runtime.api.fixtures.actor_roles import seed_project_role

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from yoke_core.domain import audiences, inbox_posts
from yoke_core.domain.inbox_post_schema import create_inbox_post_table


@pytest.fixture
def conn():
    with decision_request_connection() as value:
        create_inbox_post_table(value)
        yield value


def post(conn, **overrides):
    kwargs = dict(
        actor_id=2,
        project_id=10,
        title="Read the request",
        body="Plain text",
        source="External form",
        fields={"contact": "person@example.test", "details": [1, True]},
        rules=[
            {"scope_kind": "actor", "scope_id": 2},
            {"scope_kind": "org", "scope_id": 1, "role_name": "admin"},
        ],
    )
    kwargs.update(overrides)
    return inbox_posts.create_post(conn, **kwargs)


def test_post_visible_to_live_audience_until_shared_done(conn):
    row = post(conn)
    assert [value["id"] for value in inbox_posts.open_posts(conn, actor_id=2)] == [
        row["id"]
    ]
    assert [value["id"] for value in inbox_posts.open_posts(conn, actor_id=5)] == [
        row["id"]
    ]
    assert inbox_posts.open_posts(conn, actor_id=1) == []
    assert inbox_posts.open_posts(conn, actor_id=2, project_ids=[]) == []
    assert row["fields"] == {"contact": "person@example.test", "details": [1, True]}
    conn.execute("UPDATE inbox_posts SET created_at='2000-01-01T00:00:00Z'")
    assert len(inbox_posts.open_posts(conn, actor_id=2)) == 1
    done = inbox_posts.done_post(conn, post_id=row["id"], actor_id=5)
    assert done["done_actor_id"] == 5 and done["done_at"]
    assert not done["already_done"]
    assert inbox_posts.open_posts(conn, actor_id=2) == []
    second = inbox_posts.done_post(conn, post_id=row["id"], actor_id=2)
    assert second["already_done"]
    assert (second["done_actor_id"], second["done_at"]) == (
        done["done_actor_id"],
        done["done_at"],
    )


def test_role_loss_changes_visibility_and_done_authority(conn):
    row = post(
        conn, rules=[{"scope_kind": "project", "scope_id": 10, "role_name": "owner"}]
    )
    conn.execute("DELETE FROM actor_project_roles WHERE actor_id=2")
    assert inbox_posts.open_posts(conn, actor_id=2) == []
    with pytest.raises(PermissionError, match="permission_denied"):
        inbox_posts.done_post(conn, post_id=row["id"], actor_id=2)
    conn.execute("INSERT INTO actor_project_roles VALUES (5, 10, 1, 'now')")
    assert len(inbox_posts.open_posts(conn, actor_id=5)) == 1
    inbox_posts.done_post(conn, post_id=row["id"], actor_id=5)


def test_posting_requires_write_even_when_addressed_and_done_requires_membership(conn):
    with pytest.raises(PermissionError, match="permission_denied.*Recovery"):
        post(conn, actor_id=4, rules=[{"scope_kind": "actor", "scope_id": 4}])
    assert conn.execute("SELECT COUNT(*) FROM audiences").fetchone()[0] == 0
    row = post(conn, rules=[{"scope_kind": "actor", "scope_id": 5}])
    with pytest.raises(PermissionError, match="not_in_audience.*Recovery"):
        inbox_posts.done_post(conn, post_id=row["id"], actor_id=2)
    assert conn.execute("SELECT done_at FROM inbox_posts").fetchone()[0] is None


def test_named_unknown_empty_and_foreign_audience(conn):
    audience_id = audiences.create_audience(
        conn,
        project_id=10,
        name="Team",
        rules=[{"scope_kind": "project", "scope_id": 10}],
    )
    row = post(conn, rules=None, audience_name="Team")
    assert row["audience_id"] == audience_id
    for overrides, reason in (
        ({"rules": None, "audience_id": 999}, "unknown_audience"),
        ({"rules": []}, "empty_audience"),
        ({"rules": None, "audience_name": "Missing"}, "unknown_audience"),
    ):
        with pytest.raises(ValueError, match=reason + ".*Recovery"):
            post(conn, **overrides)
    foreign = audiences.create_audience(
        conn, org_id=1, rules=[{"scope_kind": "org", "scope_id": 1}]
    )
    with pytest.raises(ValueError, match="audience_scope_mismatch"):
        post(conn, rules=None, audience_id=foreign)


def test_borrowed_transaction_and_failed_create_do_not_leak(conn):
    row = post(conn, commit=False)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM inbox_posts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audiences").fetchone()[0] == 0
    with pytest.raises(TypeError):
        post(conn, fields={"invalid": object()})
    assert conn.execute("SELECT COUNT(*) FROM audiences").fetchone()[0] == 0
    with pytest.raises(LookupError, match="unknown_post"):
        inbox_posts.done_post(conn, post_id=row["id"], actor_id=2)


def test_open_post_page_does_not_read_each_post_again(conn):
    from runtime.api.fixtures.statement_counter import CountingConnection

    post(conn)
    one = CountingConnection(conn)
    assert len(inbox_posts.open_posts(one, actor_id=2)) == 1
    for _ in range(5):
        post(conn)
    many = CountingConnection(conn)
    assert len(inbox_posts.open_posts(many, actor_id=2)) == 6
    assert many.count == one.count


def test_concurrent_done_records_exactly_one_first_person(test_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from yoke_core.domain import db_helpers
    from yoke_core.domain.actors import seed_human_actor
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.project_seed_test_helpers import seed_project_identities

    seed_project_identities(test_db)
    project_id = resolve_project_id(test_db, "yoke")
    actors = [
        seed_human_actor(test_db, name)
        for name in ("First reviewer", "Second reviewer")
    ]
    for actor in actors:
        seed_project_role(
            test_db, actor_id=actor, project_id=project_id, role_name="owner"
        )
    row = inbox_posts.create_post(
        test_db,
        actor_id=actors[0],
        project_id=project_id,
        title="Concurrent work",
        body="Finish once",
        source="Test",
        rules=[{"scope_kind": "actor", "scope_id": actor} for actor in actors],
    )
    start = Barrier(2)

    def finish(actor):
        with db_helpers.connect() as conn:
            start.wait(timeout=15)
            return inbox_posts.done_post(conn, post_id=row["id"], actor_id=actor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish, actor) for actor in actors]
        results = [future.result(timeout=30) for future in futures]
    assert {result["done_actor_id"] for result in results} <= set(actors)
    assert (
        len({(result["done_actor_id"], result["done_at"]) for result in results}) == 1
    )
    assert sum(not result["already_done"] for result in results) == 1
