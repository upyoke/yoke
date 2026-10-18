"""Authorization start refuses a retired machine before any code exists."""

from runtime.api import test_web_sign_in_door as door
from runtime.api.test_machine_authorization import _validate_wire
from yoke_contracts.machine_authorization import START_PATH
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import machine_registry

_clean_oidc_env = door._clean_oidc_env
db_conn = door.db_conn
client = door.client

MACHINE_ID = "5d0c2f4e-9b1a-4f4e-8a3c-6f2d1b7e9c40"
START = {"machine_id": MACHINE_ID, "machine_name": "Old laptop", "platform": "macOS"}


def _owner(conn) -> int:
    return int(conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0])


def _pending_codes(conn) -> int:
    return conn.execute(
        "SELECT count(*) FROM machine_authorization_codes WHERE machine_id=%s",
        (MACHINE_ID,),
    ).fetchone()[0]


def test_start_refuses_a_retired_machine_by_name(db_conn, client):
    owner = _owner(db_conn)
    machine_registry.register_machine(
        db_conn, machine_id=MACHINE_ID, name="Old laptop", actor_id=owner, now=utc_now()
    )
    machine_registry.retire_machine(
        db_conn, machine_id=MACHINE_ID, actor_id=owner, now=utc_now()
    )
    db_conn.commit()
    refused = client.post(START_PATH, json=START)
    assert refused.status_code == 409, refused.text
    _validate_wire(refused, "MachineAuthorizationRefused")
    assert refused.json()["error"] == "machine_retired"
    assert "`yoke connect` again" in refused.json()["message"]
    assert _pending_codes(db_conn) == 0


def test_start_still_issues_a_code_for_an_active_registered_machine(db_conn, client):
    machine_registry.register_machine(
        db_conn,
        machine_id=MACHINE_ID,
        name="Old laptop",
        actor_id=_owner(db_conn),
        now=utc_now(),
    )
    db_conn.commit()
    started = client.post(START_PATH, json=START)
    assert started.status_code == 200, started.text
    assert _pending_codes(db_conn) == 1
