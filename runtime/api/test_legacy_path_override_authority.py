"""Legacy override calls cannot bypass the registered steering-seat gate."""

import json

from runtime.api.domain.steering_claim_test_support import seed_session
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client_path_claims import _capture
from runtime.api.test_service_client_path_claims import path_claims_db as path_claims_db
from yoke_core.api.service_client_path_claims import cmd_path_claim_override


def test_legacy_override_refuses_registered_session_without_steering_seat(
    path_claims_db, monkeypatch
):
    conn = connect_test_db(path_claims_db)
    try:
        seed_session(conn, "override-worker", 1)
    finally:
        conn.close()
    monkeypatch.setenv("YOKE_SESSION_ID", "override-worker")
    rc, output = _capture(
        cmd_path_claim_override,
        "1",
        "--override-point",
        "creation",
        "--integration-target",
        "main",
        "--actor-id",
        "1",
        "--actor-reason",
        "valid collision reason",
    )
    assert rc != 0
    refusal = json.loads(output)
    assert refusal["code"] == "STEERING_SEAT_REQUIRED"
    assert "requires a live steering seat for project yoke" in refusal["message"]
    assert "yoke say --steering" in refusal["message"]
