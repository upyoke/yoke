"""Real collector admission and durable redemption across isolated HTTPS origins."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import time

from fastapi.testclient import TestClient

from runtime.api import test_frontend_events as collector_tests
from yoke_core.api import app_factory
from yoke_core.domain.frontend_events_storage import consume_attribution_handoff
from yoke_core.frontend_events.events_handoff import HANDOFF_SECONDS

ATTRIBUTION = "/api/events/attribution"
MINT = ATTRIBUTION + "/handoff"
REDEEM = MINT + "/redeem"
DESTINATION = "https://app.workbench.example.test"

database = collector_tests.database
client = collector_tests.client
headers = collector_tests.headers
ORIGIN = collector_tests.ORIGIN


def capture(client, admitted):
    response = client.post(
        ATTRIBUTION,
        headers=admitted,
        json={
            "consent": True,
            "url": ORIGIN + "/?utm_source=newsletter",
            "referrer": "",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_read_valid_absent_tampered_and_revoked_never_sets_cookie(client):
    admitted = headers(client)
    absent = client.get(ATTRIBUTION, headers=admitted)
    assert absent.json()["error"] == "attribution_absent"
    assert "set-cookie" not in absent.headers
    record = capture(client, admitted)
    verified = client.get(ATTRIBUTION, headers=admitted)
    assert verified.status_code == 200 and verified.json() == record
    assert "set-cookie" not in verified.headers
    assert verified.headers["cache-control"] == "no-store"
    name = next(iter(client.cookies.keys()))
    bad = client.get(ATTRIBUTION, headers={**admitted, "Cookie": name + "=bad.bad"})
    assert bad.json()["error"] == "attribution_invalid"
    assert "set-cookie" not in bad.headers
    client.delete(ATTRIBUTION, headers=admitted)
    assert (
        client.get(ATTRIBUTION, headers=admitted).json()["error"]
        == "attribution_absent"
    )


def test_cross_origin_handoff_mint_redeem_and_replay_after_new_app_process(
    client, database
):
    source_headers = headers(client)
    record = capture(client, source_headers)
    minted = client.post(MINT, headers=source_headers, json={"audience": DESTINATION})
    assert minted.status_code == 200 and "set-cookie" not in minted.headers
    token = minted.json()["token"]
    app = TestClient(app_factory.create_app(), base_url=DESTINATION)
    admitted = headers(app, DESTINATION)
    assert (
        app.get(ATTRIBUTION, headers=admitted).json()["error"] == "attribution_absent"
    )
    redeemed = app.post(REDEEM, headers=admitted, json={"token": token})
    assert redeemed.status_code == 200 and redeemed.json() == record
    assert "HttpOnly" in redeemed.headers["set-cookie"]
    assert app.get(ATTRIBUTION, headers=admitted).json() == record
    another = TestClient(app_factory.create_app(), base_url=DESTINATION)
    replay = another.post(REDEEM, headers=admitted, json={"token": token})
    assert replay.json()["error"] == "attribution_handoff_replayed"
    assert "set-cookie" not in replay.headers
    with database() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM frontend_attribution_redemptions"
            ).fetchone()[0]
            == 1
        )


def test_forgery_expiry_wrong_audience_and_unconsented_mint(
    client, database, monkeypatch
):
    admitted = headers(client)
    assert (
        client.post(MINT, headers=admitted, json={"audience": DESTINATION}).json()[
            "error"
        ]
        == "attribution_absent"
    )
    capture(client, admitted)
    minted = client.post(MINT, headers=admitted, json={"audience": DESTINATION})
    token = minted.json()["token"]
    wrong = client.post(REDEEM, headers=admitted, json={"token": token})
    assert wrong.json()["error"] == "attribution_handoff_audience_mismatch"
    app = TestClient(app_factory.create_app(), base_url=DESTINATION)
    destination_headers = headers(app, DESTINATION)
    forged = app.post(REDEEM, headers=destination_headers, json={"token": token + "x"})
    assert forged.json()["error"] == "attribution_handoff_invalid"
    now = time.time()
    monkeypatch.setattr(
        "yoke_core.frontend_events.events_handoff.time.time",
        lambda: now + HANDOFF_SECONDS + 1,
    )
    expired = app.post(REDEEM, headers=destination_headers, json={"token": token})
    assert expired.json()["error"] == "attribution_handoff_expired"
    for response in (wrong, forged, expired):
        assert "set-cookie" not in response.headers and response.json()["recovery"]
    with database() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM frontend_attribution_redemptions"
            ).fetchone()[0]
            == 0
        )


def test_atomic_durable_nonce_consumption(database, client):
    headers(client)  # initialize the signing identity
    with database() as conn:
        org = conn.execute(
            "SELECT id FROM organizations ORDER BY id LIMIT 1"
        ).fetchone()[0]
    nonce, expires = str(uuid4()), int(time.time()) + HANDOFF_SECONDS
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: consume_attribution_handoff(org, nonce, expires), range(4)
            )
        )
    assert results.count(True) == 1 and results.count(False) == 3


def test_storage_failure_is_named_and_never_reports_redemption(client, monkeypatch):
    from yoke_core.api.routes import frontend_events

    admitted = headers(client)
    capture(client, admitted)
    token = client.post(MINT, headers=admitted, json={"audience": ORIGIN}).json()[
        "token"
    ]

    def fail(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(frontend_events, "consume_attribution_handoff", fail)
    response = client.post(REDEEM, headers=admitted, json={"token": token})
    assert response.status_code == 503
    assert response.json()["error"] == "attribution_handoff_unavailable"
    assert "set-cookie" not in response.headers


def test_deployed_probe_checks_real_routes_with_isolated_jars(
    database, monkeypatch, capsys
):
    from ops.qa import attribution_transfer

    monkeypatch.setattr(
        attribution_transfer.httpx,
        "Client",
        lambda **kwargs: TestClient(app_factory.create_app(), base_url=ORIGIN),
    )
    attribution_transfer.prove(ORIGIN, ORIGIN)
    assert "attribution transfer passed" in capsys.readouterr().out
