"""The operating-actor binding: recorded by id, proven per universe.

Every test here is about one rule — a session's identity is an actor id
this machine recorded, never something inferred from a login or a name —
and about the two ways that recorded id can stop being trustworthy: the
actor is gone, or the connection now reaches a different universe.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import session_actor_binding as binding_module
from yoke_core.domain.actors import seed_human_actor, set_actor_name
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.session_actor_binding import (
    ACTOR_MISSING,
    ACTOR_UNBOUND,
    ACTOR_UNIVERSE_MISMATCH,
    ACTOR_UNIVERSE_UNPROVEN,
    resolve_operating_actor,
)
from yoke_core.domain.session_actor_binding_write import (
    converge_operating_actor_binding,
    persist_operating_actor,
)
from yoke_core.domain.universe_identity import universe_fingerprint
from yoke_contracts.machine_config.schema_connections import (
    MachineConfigContractError,
)

ENV = "local"


@pytest.fixture
def conn(test_db):
    """The full-schema fixture, with this universe's identity card seeded.

    ``test_db`` already seeds the canonical actors, so the universe
    arrives in the shape a born one has: one human, one system actor.
    """
    seed_default_org(test_db)
    test_db.commit()
    return test_db


def _sole_human(conn) -> int:
    return int(
        conn.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """A machine config carrying one configured connection and no binding."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "active_env": ENV,
                "connections": {ENV: {"transport": "local-postgres"}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _recorded(config_path: Path) -> dict:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return payload["connections"][ENV].get("operating_actor") or {}


def test_no_recorded_binding_refuses_and_names_the_bind_command(
    conn, config_path
):
    seed_human_actor(conn, "Ada Lovelace")

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert not result.bound
    assert result.code == ACTOR_UNBOUND
    assert "yoke config bind-actor" in result.detail


def test_a_sole_human_is_not_a_standing_fallback(conn, config_path):
    """The one case that is unambiguous is still not answered implicitly."""
    assert _sole_human(conn)

    assert not resolve_operating_actor(
        conn, env=ENV, config_path=config_path
    ).bound


def test_a_recorded_binding_resolves_by_id(conn, config_path):
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert result.actor_id == actor_id
    assert _recorded(config_path)["actor_id"] == actor_id
    assert _recorded(config_path)["universe"] == universe_fingerprint(conn)


def test_renaming_the_bound_actor_changes_nothing(conn, config_path):
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    set_actor_name(conn, actor_id, "Ada King")

    assert (
        resolve_operating_actor(conn, env=ENV, config_path=config_path).actor_id
        == actor_id
    )


def test_a_second_human_sharing_the_name_is_never_selected(conn, config_path):
    bound = seed_human_actor(conn, "Ada Lovelace")
    other = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, bound, env=ENV, config_path=config_path)

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert result.actor_id == bound
    assert result.actor_id != other


def test_a_binding_naming_a_removed_actor_refuses(conn, config_path):
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)
    # Somebody still has to exist, or the earlier no-humans refusal fires.
    seed_human_actor(conn, "Grace Hopper")
    conn.execute("DELETE FROM actors WHERE id = %s", (actor_id,))
    conn.commit()

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert not result.bound
    assert "yoke config bind-actor" in result.detail


def test_a_retargeted_connection_refuses_rather_than_binding_a_stranger(
    conn, config_path
):
    """The env label is a nickname; the universe it named is the fact."""
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["connections"][ENV]["operating_actor"]["universe"] = "elsewhere@2020"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert not result.bound
    assert result.code == ACTOR_UNIVERSE_MISMATCH
    assert "elsewhere@2020" in result.detail


def test_a_recorded_binding_with_no_universe_is_unproven_not_accepted(
    conn, config_path
):
    """Silence about the universe is an unanswered question, not a pass."""
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["connections"][ENV]["operating_actor"].pop("universe")
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert not result.bound
    assert result.code == ACTOR_UNIVERSE_UNPROVEN


def test_a_control_plane_that_cannot_state_its_identity_is_unproven(
    conn, config_path
):
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    # A universe carries exactly one identity card; two answers no question.
    conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('second', 'Second', '2026-01-01T00:00:00Z')"
    )
    conn.commit()

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert not result.bound
    assert result.code == ACTOR_UNIVERSE_UNPROVEN


def test_persisting_refuses_when_the_universe_cannot_identify_itself(
    conn, config_path
):
    """Refused at write time, so no unprovable binding is ever recorded."""
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    conn.execute("DELETE FROM projects")
    conn.execute("DELETE FROM organizations")
    conn.commit()

    with pytest.raises(MachineConfigContractError):
        persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    assert _recorded(config_path) == {}


def test_persisting_refuses_an_env_this_machine_has_not_configured(
    conn, config_path
):
    actor_id = seed_human_actor(conn, "Ada Lovelace")

    with pytest.raises(MachineConfigContractError):
        persist_operating_actor(
            conn, actor_id, env="not-configured", config_path=config_path
        )


def test_no_human_actor_refuses_before_asking_about_a_binding(conn, config_path):
    conn.execute("DELETE FROM actors WHERE kind = 'human'")
    conn.commit()

    result = resolve_operating_actor(conn, env=ENV, config_path=config_path)

    assert result.code == ACTOR_MISSING


def test_converge_records_the_binding_a_single_owner_leaves_in_no_doubt(
    conn, config_path
):
    actor_id = _sole_human(conn)

    assert (
        converge_operating_actor_binding(conn, env=ENV, config_path=config_path)
        == actor_id
    )
    assert (
        resolve_operating_actor(conn, env=ENV, config_path=config_path).actor_id
        == actor_id
    )


def test_converge_declines_to_choose_between_several_humans(conn, config_path):
    seed_human_actor(conn, "Ada Lovelace")
    seed_human_actor(conn, "Grace Hopper")

    assert (
        converge_operating_actor_binding(conn, env=ENV, config_path=config_path)
        is None
    )
    assert _recorded(config_path) == {}


def test_converge_never_overwrites_an_existing_binding(conn, config_path):
    actor_id = seed_human_actor(conn, "Ada Lovelace")
    persist_operating_actor(conn, actor_id, env=ENV, config_path=config_path)

    assert (
        converge_operating_actor_binding(conn, env=ENV, config_path=config_path)
        is None
    )
    assert _recorded(config_path)["actor_id"] == actor_id


def test_no_os_login_rung_survives(conn):
    """The login-matching resolution rung is gone, not merely bypassed."""
    assert not hasattr(binding_module, "os_login")
