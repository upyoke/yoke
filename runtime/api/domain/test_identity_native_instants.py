"""Identity and release clocks stay native until owned projections."""

from dataclasses import asdict
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import parse_instant, temporal_wire
from yoke_core.domain import actor_invites, external_identities, release_notes

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_invite_and_external_identity_clocks_are_native(test_db, monkeypatch, zone):
    from yoke_core.domain.actors import seed_human_actor

    actor_id = seed_human_actor(test_db)
    org_id = external_identities.default_org_id(test_db)
    monkeypatch.setattr(actor_invites, "utc_now", lambda: STAMP)
    monkeypatch.setattr(external_identities, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    invite = actor_invites.create_invite(
        test_db, email="clock@example.test", org_id=org_id, invited_by_actor_id=actor_id
    )
    assert invite.created_at == STAMP
    assert invite.accepted_at is None
    projected = temporal_wire(asdict(invite))
    assert projected["created_at"] == "1969-12-31T23:59:59.123456Z"
    assert projected["accepted_at"] is None
    monkeypatch.setattr(
        actor_invites, "utc_now", lambda: STAMP + timedelta(microseconds=1)
    )
    accepted = actor_invites.mark_invite_accepted(
        test_db, invite_id=invite.invite_id, accepted_by_actor_id=actor_id
    )
    assert accepted.accepted_at == STAMP + timedelta(microseconds=1)
    link = external_identities.link_external_identity(
        test_db, actor_id=actor_id, issuer="clock-issuer", subject="clock-subject"
    )
    assert (
        test_db.execute(
            "SELECT linked_at FROM actor_external_identities WHERE id=%s", (link,)
        ).fetchone()[0]
        == STAMP
    )


def test_release_note_pipe_projection_has_canonical_clock(test_db, monkeypatch):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    monkeypatch.setattr(release_notes, "utc_now", lambda: STAMP)
    release_notes.cmd_insert(
        test_db, 7, "features", "Native clock", "2026-10-09", "yoke"
    )
    assert (
        test_db.execute(
            "SELECT created_at FROM release_entries WHERE item_id=%s", (7,)
        ).fetchone()[0]
        == STAMP
    )
    assert release_notes.cmd_list(test_db, "2026-10-09", "yoke").endswith(
        "|1969-12-31T23:59:59.123456Z"
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_permission_seed_clocks_are_native(test_db, monkeypatch, zone):
    from yoke_core.domain import actor_permissions

    monkeypatch.setattr(actor_permissions, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    for table in (
        "actor_org_roles",
        "actor_project_roles",
        "role_permissions",
        "roles",
        "permissions",
    ):
        test_db.execute(f"DELETE FROM {table}")
    actor_permissions.seed_roles_and_permissions(test_db)
    for table in ("roles", "permissions", "role_permissions"):
        clocks = test_db.execute(f"SELECT created_at FROM {table}").fetchall()
        assert clocks
        assert all(row[0] == STAMP for row in clocks)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_actor_birth_clocks_preserve_microseconds(test_db, monkeypatch, zone):
    from yoke_core.domain import actors

    monkeypatch.setattr(actors, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor_id = actors.seed_human_actor(test_db, name="Native clock")
    system_id = actors.seed_system_actor(test_db, system_component="native-clock-test")
    for identity in (actor_id, system_id):
        assert (
            test_db.execute(
                "SELECT created_at FROM actors WHERE id=%s", (identity,)
            ).fetchone()[0]
            == STAMP
        )
