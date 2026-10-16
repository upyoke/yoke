"""Short-code connection delivers one credential through the public wire."""

from runtime.api import test_self_host_workbench as workbench
from yoke_contracts.machine_authorization import POLL_PATH, START_PATH
from yoke_core.domain.actor_role_grants import grant_actor_org_role
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.machine_match_codes import MATCH_CODE_ALPHABET

_no_oidc = workbench._no_oidc
db_conn = workbench.db_conn
actor_id = workbench.actor_id
browser = workbench.browser
IDENTITY = {
    "machine_id": "762fb8a5-7a6f-43e0-ae85-9665af3fe871",
    "machine_name": "Connecting laptop",
}


def test_start_approve_poll_binds_credential_to_signed_in_member(
    db_conn, browser, actor_id
):
    register_all_handlers()
    grant_actor_org_role(
        db_conn, actor_id=actor_id, org_id=default_org_id(db_conn), role_name="viewer"
    )
    started = browser.post(START_PATH, json={**IDENTITY, "platform": "Linux"})
    assert started.status_code == 200, started.text
    authorization = started.json()
    assert len(authorization["user_code"]) == 4
    assert set(authorization["user_code"]) <= set(MATCH_CODE_ALPHABET)
    assert authorization["expires_in"] == 600
    poll_body = {"device_code": authorization["device_code"], **IDENTITY}
    waiting = browser.post(POLL_PATH, json=poll_body)
    assert waiting.status_code == 202
    assert waiting.json()["error"] == "authorization_pending"
    approved = workbench._call(
        browser,
        "machine_authorization.resolve",
        {
            "code": " " + authorization["user_code"].lower() + " ",
            "action": "approve",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"]["authorization"] == {"decision": "approve"}
    delivered = browser.post(POLL_PATH, json=poll_body)
    assert delivered.status_code == 200, delivered.text
    credential = delivered.json()
    assert credential["api_url"] == "http://testserver"
    assert credential["token"]
    row = db_conn.execute(
        "SELECT actor_id,machine_id FROM api_tokens WHERE machine_id=%s",
        (IDENTITY["machine_id"],),
    ).fetchone()
    assert tuple(row) == (actor_id, IDENTITY["machine_id"])
    consumed = browser.post(POLL_PATH, json=poll_body)
    assert consumed.status_code == 410
    assert consumed.json()["error"] == "authorization_consumed"
    assert (
        db_conn.execute(
            "SELECT count(*) FROM decision_requests WHERE kind='machine_auth_request'"
        ).fetchone()[0]
        == 0
    )
