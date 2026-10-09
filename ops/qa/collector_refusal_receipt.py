"""Prove the deployed collector records refusals and stamps receipt time.

One deliberately refused write (a wrong publishable key from the public origin,
so the hosted relay forwards it to the engine) must appear as a
FrontendCollectorRefused event, and one page view sent with a client clock an
hour behind must be stored with the collector's receipt time, the client time
kept in its envelope, and the client_time_skew flag. Rows are read through
`yoke db read`, so the runner's control-plane connection must be the deployed
universe; a page view it cannot find is reported as that mismatch. No
publishable key or cookie value is logged.
"""

import argparse
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from ops.qa.attribution_transfer import target
from ops.qa.hosted_origin_admission import expect, page_view

SKEW = timedelta(hours=1)
REFUSAL_WAIT_SECONDS = 15


def read(sql):
    result = subprocess.run(
        ["yoke", "db", "read", sql], text=True, capture_output=True, check=False
    )
    try:
        envelope = json.loads(result.stdout)
        if result.returncode:
            raise ValueError()
        return envelope["rows"]
    except (ValueError, KeyError) as error:
        raise ValueError(
            "collector_probe_read_failed: restore `yoke db read` on the runner's "
            "control-plane connection and rerun the case"
        ) from error


def stored_view(event_id):
    rows = read(
        "SELECT created_at, anomaly_flags, envelope::jsonb ->> 'event_time', "
        "envelope::jsonb ->> 'received_at' FROM events "
        f"WHERE event_id = '{event_id}'"
    )
    if not rows:
        raise ValueError(
            "collector_probe_universe_mismatch: the accepted page view is not in "
            "the runner's universe; run the case with the deployed universe's connection"
        )
    return rows[0]


def recorded_refusal(since):
    deadline = time.monotonic() + REFUSAL_WAIT_SECONDS
    while True:
        rows = read(
            "SELECT created_at FROM events WHERE event_name = "
            "'FrontendCollectorRefused' AND event_outcome = 'publishable_key_invalid' "
            f"AND created_at >= '{since}' ORDER BY created_at DESC LIMIT 1"
        )
        if rows:
            return rows[0][0]
        if time.monotonic() > deadline:
            raise ValueError(
                "collector_refusal_not_recorded: a refused write left no "
                "FrontendCollectorRefused event; check the engine log for "
                "collector_refusal_record_failed"
            )
        time.sleep(1)


def prove(origin, api):
    started = datetime.now(timezone.utc) - timedelta(minutes=2)
    with httpx.Client(timeout=20) as client:
        config = client.get(api + "/api/events/config")
        expect(config, 200)
        key = config.json()["publishableKey"]
        refused = {"Origin": origin, "X-Events-Key": key + "-qa-invalid"}
        expect(
            client.post(api + "/api/events", headers=refused, json=page_view(origin)),
            401,
            "publishable_key_invalid",
        )
        view = page_view(origin)
        sent = view["events"][0]
        sent["event_time"] = (datetime.now(timezone.utc) - SKEW).isoformat()
        sent["page_url"] = origin + "/?qa=collector-receipt-time"
        admitted = {"Origin": origin, "X-Events-Key": key}
        expect(client.post(api + "/api/events", headers=admitted, json=view), 200)
    refusal_at = recorded_refusal(started.strftime("%Y-%m-%dT%H:%M:%S"))
    created, flags, client_time, received = stored_view(sent["event_id"])
    if not received or created != received or client_time != sent["event_time"]:
        raise ValueError(
            "collector_receipt_time_missing: created_at must equal the envelope "
            "received_at while event_time keeps the client clock"
        )
    if flags != "client_time_skew":
        raise ValueError(
            "collector_skew_unflagged: a client clock an hour off must carry "
            "anomaly_flags=client_time_skew"
        )
    print(
        f"collector refusal recorded at {refusal_at}; page view stored at receipt "
        f"{received} with client event_time {client_time} flagged client_time_skew"
    )


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
            else "collector_probe_unavailable: restore deployed collector access and rerun the case"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
