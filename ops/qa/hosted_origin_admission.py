"""Prove the deployed hosted collector admits only its public browser origin.

Behind the hosted relay the engine sees its upstream address as Host, so this
passes only when trusted forwarding restores the public host. The hosted relay
rewrites Origin on reads and refuses foreign-origin writes itself, so the
foreign-origin checks are writes. One page view is written, marked by its URL;
no publishable key or cookie value is logged.
"""

import argparse
from uuid import uuid4

import httpx

from yoke_contracts.timestamps import format_instant, utc_now

from ops.qa.attribution_transfer import target

FOREIGN_ORIGIN = "https://foreign-origin.invalid"


def error_code(response):
    try:
        return response.json().get("error")
    except ValueError:
        return None  # A non-JSON body is reported as the status change below.


def expect(response, status, reason=None):
    if response.status_code != status or (reason and error_code(response) != reason):
        raise ValueError(
            f"hosted_origin_probe_status_changed: expected {status}"
            f"{' ' + reason if reason else ''}, got {response.status_code}; "
            "check YOKE_API_TRUSTED_PROXIES and X-Forwarded-Host at the hosted relay"
        )


def expect_refused(response):
    expect(response, 403, "origin_not_allowed")
    if "set-cookie" in response.headers:
        raise ValueError(
            "hosted_origin_probe_cookie_mutated: a refused foreign-origin write "
            "must never set a cookie"
        )


def page_view(origin):
    return {
        "events": [
            {
                "event_id": str(uuid4()),
                "event_name": "PageViewed",
                "event_kind": "analytics",
                "event_type": "page_view",
                "event_time": format_instant(utc_now()),
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
        expect_refused(
            client.post(api + "/api/events", headers=foreign, json=page_view(origin))
        )
        expect_refused(
            client.post(
                attribution,
                headers=foreign,
                json={"url": origin + "/?qa=hosted-origin-admission", "referrer": ""},
            )
        )
    print(
        "hosted origin admission passed: public origin admitted for attribution "
        "and page views; foreign-origin writes refused"
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
