"""Prove the deployed collector classifies devices from the request User-Agent.

Each probe page view goes through the public origin (the hosted relay forwards
User-Agent to the engine) with a real device's User-Agent and an emitter
device_type deliberately set to the wrong value. The stored envelope must carry
the collector's browser, os and device_type for that User-Agent, never the
emitter's. Rows are read through `yoke db read`, so the runner's control-plane
connection must be the deployed universe. No publishable key is logged.
"""

import argparse
import json
import subprocess

import httpx

from ops.qa.attribution_transfer import target
from ops.qa.hosted_origin_admission import expect, page_view

DEVICES = (
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        ("Chrome", "macOS", "desktop"),
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Claude/1.0.211 Chrome/138.0.7204.251 "
        "Electron/37.6.0 Safari/537.36",
        ("Electron", "macOS", "desktop"),
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
        "Mobile/15E148 Safari/604.1",
        ("Mobile Safari", "iOS", "mobile"),
    ),
    (
        "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        ("Mobile Safari", "iOS", "tablet"),
    ),
)


def stored_device(event_id):
    result = subprocess.run(
        [
            "yoke",
            "db",
            "read",
            "SELECT envelope::jsonb ->> 'browser', envelope::jsonb ->> 'os', "
            "envelope::jsonb ->> 'device_type' FROM events "
            f"WHERE event_id = '{event_id}'",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        envelope = json.loads(result.stdout)
        if result.returncode:
            raise ValueError()
        rows = envelope["rows"]
    except (ValueError, KeyError) as error:
        raise ValueError(
            "device_probe_read_failed: restore `yoke db read` on the runner's "
            "control-plane connection and rerun the case"
        ) from error
    if not rows:
        raise ValueError(
            "device_probe_universe_mismatch: the accepted page view is not in the "
            "runner's universe; run the case with the deployed universe's connection"
        )
    return tuple(rows[0])


def prove(origin, api):
    sent = []
    with httpx.Client(timeout=20) as client:
        config = client.get(api + "/api/events/config")
        expect(config, 200)
        key = config.json()["publishableKey"]
        for user_agent, expected in DEVICES:
            view = page_view(origin)
            event = view["events"][0]
            event["page_url"] = origin + "/?qa=collector-device-classification"
            event["device_type"] = "mobile" if expected[2] == "desktop" else "desktop"
            headers = {"Origin": origin, "X-Events-Key": key, "User-Agent": user_agent}
            expect(client.post(api + "/api/events", headers=headers, json=view), 200)
            sent.append((event["event_id"], expected))
    for event_id, expected in sent:
        stored = stored_device(event_id)
        if stored != expected:
            raise ValueError(
                f"device_classification_wrong: expected browser/os/device_type "
                f"{expected}, stored {stored} for event {event_id}; check that the "
                "relay forwards User-Agent and the engine runs Pack 4.4.0"
            )
        print(f"{event_id}: {'/'.join(stored)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    try:
        prove(*target(args.plan, args.project))
    except (ValueError, httpx.HTTPError) as error:
        print(
            str(error)
            if isinstance(error, ValueError)
            else "device_probe_unavailable: restore deployed collector access and rerun the case"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
