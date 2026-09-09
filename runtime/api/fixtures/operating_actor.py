"""The operating-actor binding a fixture universe records about itself.

A born universe knows two things about its owner: the actor row exists,
and this machine has recorded that it operates the universe as that
actor. Registration reads the second by id — it does not infer one from
an OS login or a name — so a fixture that seeds only the first models a
machine no session can register against, which is not the install those
tests mean to describe.

The writer lives here rather than beside either fixture because both the
backlog fixture and the API auth helper seed a universe, and a binding
written two ways is a binding that drifts.
"""

from __future__ import annotations

import os
from typing import Any


#: The connection label a fixture universe is reached under. Registration
#: resolves the operating actor per connection, so the fixture needs one
#: to record the binding against, exactly as a real machine does.
FIXTURE_ENV = "local"


def record_fixture_operating_actor(conn: Any, actor_id: int) -> None:
    """Record the operating-actor binding a born universe already carries.

    This writes a machine config, so it writes ONLY where the machine
    home has been redirected for the test. Without that guard the write
    lands in the operator's own ``~/.yoke/config.json`` — adding a
    connection and an operating actor to the config their real sessions
    read — and any test process that later reads it takes a different
    branch than it would on a clean machine, which is how a local-postgres
    connection appeared under a harness test that never asked for one.

    A fixture whose schema carries no organization identity card cannot
    state which universe it is, so no binding is recorded and its tests
    get the refusal a real machine would. Both skips are checked for by
    name rather than caught: swallowing the write's own failure once hid
    a missing identity card through a whole CI round, and any other
    failure here is a defect that should surface at the fixture.
    """
    from yoke_contracts.machine_config import runtime as machine_config
    from yoke_core.domain.session_actor_binding_write import (
        persist_operating_actor,
    )
    from yoke_core.domain.universe_identity import universe_fingerprint

    redirected = any(
        os.environ.get(name)
        for name in (machine_config.CONFIG_FILE_ENV, machine_config.HOME_ENV)
    )
    if not redirected or universe_fingerprint(conn) is None:
        return

    config_path = machine_config.config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(machine_config.load_config())
    connections = dict(payload.get("connections") or {})
    connections.setdefault(FIXTURE_ENV, {"transport": "local-postgres"})
    payload["connections"] = connections
    payload.setdefault("active_env", FIXTURE_ENV)
    machine_config.write_config(config_path, payload)
    persist_operating_actor(conn, actor_id, env=FIXTURE_ENV)


def seed_fixture_universe_identity(conn: Any) -> None:
    """Give a partial fixture schema the universe identity card.

    A universe states which universe it is through its single
    organization row, and registration refuses an operating-actor
    binding it cannot prove belongs to the universe the connection
    reached. A fixture that registers sessions therefore needs the card,
    and the auth tables are what carry the organization table itself.
    """
    from yoke_core.domain.auth_schema import create_auth_tables
    from yoke_core.domain.org_schema import seed_default_org

    create_auth_tables(conn)
    seed_default_org(conn)


__all__ = [
    "FIXTURE_ENV",
    "record_fixture_operating_actor",
    "seed_fixture_universe_identity",
]
