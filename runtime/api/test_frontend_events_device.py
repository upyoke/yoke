"""The collector stamps browser, OS and device type from the request headers."""

import json

from runtime.api.test_frontend_events import client, database, event, headers  # noqa: F401

MAC_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

def test_collector_overrides_emitter_device_fields(client, database):  # noqa: F811
    payload = {**event(), "device_type": "mobile", "browser": "forged"}
    admitted = {**headers(client), "User-Agent": MAC_CHROME}
    response = client.post("/api/events", json={"events": [payload]}, headers=admitted)
    assert response.status_code == 200
    with database() as conn:
        raw = conn.execute(
            "SELECT envelope FROM events WHERE event_id=%s", (payload["event_id"],)
        ).fetchone()[0]
    stored = json.loads(raw) if isinstance(raw, str) else raw
    assert stored["device_type"] == "desktop"
    assert stored["browser"] == "Chrome"
    assert stored["browser_version"] == "141.0.0.0"
    assert stored["os"] == "macOS"
