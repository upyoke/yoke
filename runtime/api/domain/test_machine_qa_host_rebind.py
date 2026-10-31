"""Cloud address CAS preserves verification and requires the session host lease."""

import json

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.handlers.machine_qa_host_rebind import handle_host_rebind
from yoke_core.domain.machine_qa_golden_destination import selected_test_machine_row
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)

NAME = "mac-mini-lab"
SESSION = "session-rebind"


def _seed(conn, tmp_path, monkeypatch, *, cloud=True, desktop_host=None):
    configure_test_machine(conn, tmp_path, monkeypatch)
    seed_qa_session(conn, SESSION, "other-rebind")
    row = selected_test_machine_row(conn, project="yoke", test_machine=NAME)
    settings = {**row.settings}
    if cloud:
        settings["cloud_instance_id"] = "i-0123456789abcdef0"
    if desktop_host:
        settings.update(
            desktop_host=desktop_host,
            desktop_protocol="rdp",
            desktop_route="ssh-forward",
            desktop_user="qa",
            desktop_port="3389",
        )
    conn.execute(
        "UPDATE project_capabilities SET settings=%s WHERE project_id=1 AND type=%s",
        (json.dumps(settings), row.capability_type),
    )
    record_test_machine_verification(
        conn, 1, test_machine=NAME, status="verified", checks=[], error_code=None
    )
    conn.commit()
    return selected_test_machine_row(conn, project="yoke", test_machine=NAME)


def _call(row, *, session=SESSION, token=None):
    return handle_host_rebind(
        FunctionCallRequest(
            function="test_machine.host_rebind",
            actor=ActorContext(actor_id="1", session_id=session),
            target=TargetRef(kind="global"),
            payload={
                "project": "yoke",
                "test_machine": NAME,
                "host": "184.195.162.151",
                "base_settings": token if token is not None else row.settings_token,
            },
        )
    )


def _verification(conn, cap):
    return dict(
        conn.execute(
            "SELECT * FROM test_machine_verifications WHERE project_id=1 AND capability_type=%s",
            (cap,),
        ).fetchone()
    )


@pytest.mark.parametrize("lease_reason", ["plan case", "golden operation"])
@pytest.mark.parametrize("desktop_host", [None, "test-mac.local", "127.0.0.1"])
def test_holder_rebind_changes_only_address_and_matching_desktop(
    test_db, tmp_path, monkeypatch, lease_reason, desktop_host
):
    row = _seed(test_db, tmp_path, monkeypatch, desktop_host=desktop_host)
    acquire(test_db, host_claim_target(NAME), SESSION, reason=lease_reason)
    before = _verification(test_db, row.capability_type)
    outcome = _call(row)
    assert outcome.primary_success, outcome.error
    after = selected_test_machine_row(test_db, project="yoke", test_machine=NAME)
    expected = {**row.settings, "host": "184.195.162.151"}
    if desktop_host == row.settings["host"]:
        expected["desktop_host"] = expected["host"]
    assert after.settings == expected
    assert after.verified_at == row.verified_at
    assert _verification(test_db, row.capability_type) == before
    event = test_db.execute(
        "SELECT envelope FROM events WHERE event_name='test_machine.host_rebound' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    context = (json.loads(event[0]) if isinstance(event[0], str) else event[0])[
        "context"
    ]
    assert context["previous_host"] == row.settings["host"]
    assert context["host"] == expected["host"]
    assert context["cloud_instance_id"] == row.settings["cloud_instance_id"]


@pytest.mark.parametrize("failure", ["stale", "foreign", "not-cloud"])
def test_refusal_preserves_stored_bytes_and_verification(
    test_db, tmp_path, monkeypatch, failure
):
    row = _seed(test_db, tmp_path, monkeypatch, cloud=failure != "not-cloud")
    acquire(test_db, host_claim_target(NAME), SESSION)
    before = _verification(test_db, row.capability_type)
    outcome = _call(
        row,
        session="other-rebind" if failure == "foreign" else SESSION,
        token="stale" if failure == "stale" else None,
    )
    assert not outcome.primary_success
    assert (
        outcome.error.code
        == {
            "stale": "test_machine_settings_changed",
            "foreign": "test_machine_host_lease_required",
            "not-cloud": "test_machine_cloud_instance_required",
        }[failure]
    )
    after = selected_test_machine_row(test_db, project="yoke", test_machine=NAME)
    assert after.settings_token == row.settings_token
    assert after.verified_at == row.verified_at
    assert _verification(test_db, row.capability_type) == before
