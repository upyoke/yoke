"""Prove the deployed hosted collector admits only its public browser origin.

Behind the hosted relay the engine sees its upstream address as Host, so this
passes only when trusted forwarding restores the public host. One page view is
written, marked by its URL; no publishable key or cookie value is logged.
"""

import argparse
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from ops.qa.attribution_transfer import target

FOREIGN_ORIGIN = "https://foreign-origin.invalid"


def expect(response, status, reason=None):
    if response.status_code != status or (
        reason and response.json().get("error") != reason
    ):
        raise ValueError(
            f"hosted_origin_probe_status_changed: expected {status}"
            f"{' ' + reason if reason else ''}, got {response.status_code}; "
            "check YOKE_API_TRUSTED_PROXIES and X-Forwarded-Host at the hosted relay"
        )


def page_view(origin):
    return {
        "events": [
            {
                "event_id": str(uuid4()),
                "event_name": "PageViewed",
                "event_kind": "analytics",
                "event_type": "page_view",
                "event_time": datetime.now(timezone.utc).isoformat(),
                "session_id": str(uuid4()),
                "source_type": "frontend",
                "page_url": origin + "/?qa=hosted-origin-admission",
                "referrer": "",
            }
        ]
    }


def prove(origin, api):
    with httpx.Client(timeout=20) as client:
        config = client.get(api + "/api/events/config")
        expect(config, 200)
        key = config.json()["publishableKey"]
        admitted = {"Origin": origin, "X-Events-Key": key}
        foreign = {"Origin": FOREIGN_ORIGIN, "X-Events-Key": key}
        attribution = api + "/api/events/attribution"
        expect(client.get(attribution, headers=admitted), 400, "attribution_absent")
        expect(
            client.post(api + "/api/events", headers=admitted, json=page_view(origin)),
            200,
        )
        expect(client.get(attribution, headers=foreign), 403, "origin_not_allowed")
        expect(
            client.post(api + "/api/events", headers=foreign, json=page_view(origin)),
            403,
            "origin_not_allowed",
        )
    print(
        "hosted origin admission passed: public origin admitted for attribution "
        "and page views; foreign origin refused"
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
            else "hosted_origin_probe_unavailable: restore deployed collector access and rerun the case"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
