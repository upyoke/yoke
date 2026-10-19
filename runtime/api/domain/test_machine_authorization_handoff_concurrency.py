"""Concurrent hosted delivery uses the existing PostgreSQL consumption lock."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import threading

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.domain.machine_registry_test_support import MACHINE_ID
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.api_tokens import (
    bootstrap_admin_token,
    bootstrap_hosted_service_token,
)
from yoke_core.domain import machine_authorization_decisions as decisions
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.machine_authorization_handoff import handoff
from yoke_core.domain.machine_authorization_handoff_poll import handoff_poll


def test_concurrent_service_polls_deliver_one_token(tmp_path):
    with init_test_db(tmp_path) as token:
        with connect_test_db(token) as conn:
            service = bootstrap_hosted_service_token(conn)
            human = bootstrap_admin_token(conn)
            org_id = default_org_id(conn)
            handoff(
                conn,
                device_code_sha256=hashlib.sha256(b"concurrent-secret").hexdigest(),
                user_code="K7F2",
                machine_id=MACHINE_ID,
                machine_name="Laptop",
                platform="Linux",
                expires_at=format_instant(utc_now() + timedelta(minutes=10)),
                org_id=org_id,
                actor_id=service.actor_id,
            )
            decisions.resolve(
                conn, code="K7F2", actor_id=human.actor_id, action="approve"
            )
        ready = threading.Barrier(2)

        def poll():
            with connect_test_db(token) as conn:
                ready.wait(timeout=10)
                return handoff_poll(
                    conn,
                    device_code="concurrent-secret",
                    machine_id=MACHINE_ID,
                    machine_name="Laptop",
                    org_id=org_id,
                    actor_id=service.actor_id,
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: poll(), range(2)))
        assert sorted(x["state"] for x in results) == ["approved", "consumed"]
        assert sum("token" in x for x in results) == 1
        with connect_test_db(token) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM api_tokens WHERE machine_id=%s", (MACHINE_ID,)
                ).fetchone()[0]
                == 1
            )
