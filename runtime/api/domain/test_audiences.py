"""Audience union, live role membership, ownership and reusable names."""

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from yoke_core.domain import audiences


@pytest.fixture
def conn():
    with decision_request_connection() as value:
        yield value


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"scope_kind": "org", "scope_id": 1}, (5,)),
        ({"scope_kind": "org", "scope_id": 1, "role_name": "admin"}, (5,)),
        ({"scope_kind": "project", "scope_id": 10}, (2, 4, 5)),
        ({"scope_kind": "project", "scope_id": 10, "role_name": "owner"}, (2, 5)),
        ({"scope_kind": "actor", "scope_id": 3}, (3,)),
    ],
)
def test_rule_kinds_resolve_active_people(conn, rule, expected):
    audience_id = audiences.create_audience(conn, project_id=10, rules=[rule])
    assert (
        tuple(
            sorted(
                {row["actor_id"] for row in audiences.member_matches(conn, audience_id)}
            )
        )
        == expected
    )
    assert audiences.rule_actor_ids(conn, rule) == expected
    for actor in range(1, 7):
        assert audiences.includes_actor(conn, audience_id, actor) == (actor in expected)
        assert (audience_id in audiences.audiences_for_actor(conn, actor)) == (
            actor in expected
        )


def test_union_is_live_deduplicated_and_named_selection_excludes_inline(conn):
    rules = [
        {"scope_kind": "project", "scope_id": 10, "role_name": "operator"},
        {"scope_kind": "actor", "scope_id": 3},
        {"scope_kind": "actor", "scope_id": 5},
    ]
    audience_id = audiences.create_audience(
        conn, project_id=10, name="Reviewers", rules=rules + [rules[1]]
    )
    audiences.create_audience(conn, project_id=10, rules=[rules[1]])
    assert [row["name"] for row in audiences.named_audiences(conn, project_id=10)] == [
        "Reviewers"
    ]
    assert len(audiences.rules_for_audiences(conn, [audience_id])[audience_id]) == 3
    conn.execute("INSERT INTO actor_project_roles VALUES (4, 10, 2, 'now')")
    assert audiences.includes_actor(conn, audience_id, 4)
    assert audience_id in audiences.audiences_for_actor(conn, 4)
    conn.execute("DELETE FROM actor_project_roles WHERE actor_id=4 AND role_id=2")
    assert not audiences.includes_actor(conn, audience_id, 4)
    conn.execute("UPDATE actors SET status='retired' WHERE id=3")
    assert not audiences.includes_actor(conn, audience_id, 3)


@pytest.mark.parametrize(
    "rules,reason",
    [
        ([], "empty_audience"),
        ([{"scope_kind": "actor", "scope_id": 6}], "invalid_audience_rule"),
        ([{"scope_kind": "actor", "scope_id": 99}], "invalid_audience_rule"),
        (
            [{"scope_kind": "project", "scope_id": 10, "role_name": "missing"}],
            "invalid_audience_rule",
        ),
        ([{"scope_kind": "org", "scope_id": "1"}], "invalid_audience_rule"),
    ],
)
def test_invalid_rules_name_recovery_without_leaking_audience(conn, rules, reason):
    with pytest.raises(ValueError, match=reason + ".*Recovery"):
        audiences.create_audience(conn, project_id=10, rules=rules)
    assert conn.execute("SELECT COUNT(*) FROM audiences").fetchone()[0] == 0


def test_scope_and_name_refusals_and_borrowed_rollback(conn):
    conn.execute("INSERT INTO organizations VALUES (2, 'other', 'Other', 'now')")
    with pytest.raises(ValueError, match="audience_scope_mismatch"):
        audiences.create_audience(
            conn, project_id=10, rules=[{"scope_kind": "org", "scope_id": 2}]
        )
    audiences.create_audience(
        conn,
        project_id=10,
        name="Team",
        rules=[{"scope_kind": "project", "scope_id": 10}],
    )
    with pytest.raises(ValueError, match="audience_name_exists"):
        audiences.create_audience(
            conn,
            project_id=10,
            name="Team",
            rules=[{"scope_kind": "project", "scope_id": 10}],
        )
    with pytest.raises(ValueError, match="unknown_audience"):
        audiences.audience(conn, 999)
    audience_id = audiences.create_audience(
        conn,
        project_id=10,
        name="Temporary",
        rules=[{"scope_kind": "actor", "scope_id": 2}],
        commit=False,
    )
    conn.rollback()
    with pytest.raises(ValueError, match="unknown_audience"):
        audiences.audience(conn, audience_id)


def test_org_roles_inherit_only_into_their_own_projects(conn):
    conn.execute("INSERT INTO organizations VALUES (2, 'other', 'Other', 'now')")
    conn.execute(
        "INSERT INTO projects VALUES (11, 'second', 'Second', 'SEC', 1, 'now')"
    )
    conn.execute("INSERT INTO projects VALUES (12, 'other', 'Other', 'OTH', 2, 'now')")
    conn.execute("INSERT INTO actor_org_roles VALUES (3, 1, 2, 'now')")
    for project in (10, 11):
        for role in ("operator", "viewer"):
            assert 3 in audiences.rule_actor_ids(
                conn,
                {
                    "scope_kind": "project",
                    "scope_id": project,
                    "role_name": role,
                },
            )
        for role in ("owner", "admin"):
            assert 3 not in audiences.rule_actor_ids(
                conn,
                {
                    "scope_kind": "project",
                    "scope_id": project,
                    "role_name": role,
                },
            )
    assert not audiences.rule_actor_ids(
        conn,
        {
            "scope_kind": "project",
            "scope_id": 12,
            "role_name": "viewer",
        },
    )
    conn.execute("UPDATE actors SET status='disabled' WHERE id=3")
    assert 3 not in audiences.rule_actor_ids(
        conn,
        {
            "scope_kind": "project",
            "scope_id": 10,
            "role_name": "operator",
        },
    )
