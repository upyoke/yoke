"""Trusted client context enriches envelopes without gating collection."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.frontend_events_test_support import client, database, event, headers  # noqa: F401
from yoke_core.api import frontend_events_geo as geo


@pytest.mark.parametrize("mode", ["configured", "unset", "missing", "broken", "no_match"])
def test_collector_geo_uses_client_and_discards_forged_fields(
    client, database, monkeypatch, mode  # noqa: F811
):
    seen = []
    for setting in ("YOKE_GEOIP_CITY_DB", "YOKE_GEOIP_ASN_DB"):
        if mode == "unset":
            monkeypatch.delenv(setting, raising=False)
        else:
            monkeypatch.setenv(setting, setting)

    class Reader:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            if mode == "missing":
                raise FileNotFoundError()
            return self

        def __exit__(self, *args):
            pass

        def get(self, address):
            seen.append(address)
            if mode == "broken":
                raise ValueError("unreadable record")
            if mode == "no_match":
                return None
            if self.path.endswith("ASN_DB"):
                return {"autonomous_system_organization": "Example Network"}
            return {
                "country": {"iso_code": "US"},
                "subdivisions": [{"names": {"en": "California"}}],
                "city": {"names": {"en": "Los Angeles"}},
            }

    monkeypatch.setattr(geo.maxminddb, "open_database", Reader)
    payload = {**event(), **dict.fromkeys(geo.GEO_FIELDS, "forged")}
    admitted = {**headers(client), "X-Forwarded-For": "198.51.100.2",
                "X-Real-IP": "198.51.100.3"}
    response = client.post("/api/events", json={"events": [payload]}, headers=admitted)
    assert response.status_code == 200
    with database() as conn:
        raw = conn.execute(
            "SELECT envelope FROM events WHERE event_id=%s", (payload["event_id"],)
        ).fetchone()[0]
    stored = json.loads(raw)
    assert stored["client_ip"] == "testclient"
    assert all(address == "testclient" for address in seen)
    if mode == "configured":
        assert {key: stored[key] for key in geo.GEO_FIELDS} == {
            "client_ip": "testclient", "geo_country": "US",
            "geo_region": "California", "geo_city": "Los Angeles",
            "network_org": "Example Network",
        }
    else:
        assert not (geo.GEO_FIELDS - {"client_ip"}) & stored.keys()


def test_no_client_has_no_geo():
    assert geo.geo_props(None) == {}
    assert geo.geo_props(SimpleNamespace(host="")) == {}
