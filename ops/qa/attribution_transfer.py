"""Prove deployed verified attribution routes using isolated, disposable cookie jars.

Read the plan's declared application endpoint and tenant rather than assuming
that the distribution host named by BASE_URL serves tenant collector routes.
No signing key, browser token, visitor id or attribution payload is logged.
"""

import argparse
import json
import os
import subprocess
from urllib.parse import quote, urlsplit

import httpx


def target(plan, project):
    base = os.environ.get("BASE_URL", "").rstrip("/")
    if (
        not base
        or not os.environ.get("DEPLOYMENT_RUN_ID")
        or not os.environ.get("DEPLOYMENT_MEMBER_REF")
    ):
        raise ValueError(
            "attribution_probe_subject_missing: run the item-scoped deployed QA case"
        )
    result = subprocess.run(
        ["yoke", "qa", "plan", "get", plan, "--project", project, "--full", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        envelope = json.loads(result.stdout)
        if result.returncode or not envelope["success"]:
            raise ValueError()
        execution = envelope["result"]["plan"]["execution_target"]
        endpoints = execution["endpoints"]
        app = endpoints["app_url"].rstrip("/")
        tenant = execution["tenant"]["slug"]
        if (
            base not in {app, endpoints["api_url"].rstrip("/")}
            or urlsplit(app).scheme != "https"
            or not tenant
        ):
            raise ValueError()
        return app, app + "/api/orgs/" + quote(tenant, safe="")
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(
            "attribution_probe_target_mismatch: restore the QA plan's declared HTTPS app and tenant target"
        ) from error


def check(response, expected=200, reason=None, no_cookie=False):
    if response.status_code != expected:
        raise ValueError(
            "attribution_probe_http_refused: inspect the deployed collector and restore the expected route/status"
        )
    if no_cookie and "set-cookie" in response.headers:
        raise ValueError(
            "attribution_probe_cookie_mutated: verified reads and refused transfers must never set a cookie"
        )
    if response.headers.get("cache-control") != "no-store":
        raise ValueError(
            "attribution_probe_cacheable: restore no-store on attribution responses"
        )
    data = response.json()
    if reason and data.get("error") != reason:
        raise ValueError(
            "attribution_probe_refusal_changed: restore the documented named refusal"
        )
    return data


def prove(origin, api):
    attribution = api + "/api/events/attribution"
    mint, redeem = attribution + "/handoff", attribution + "/handoff/redeem"
    with httpx.Client(timeout=20) as source, httpx.Client(timeout=20) as destination:
        config = source.get(api + "/api/events/config")
        config.raise_for_status()
        admitted = {"Origin": origin, "X-Events-Key": config.json()["publishableKey"]}
        check(
            source.get(attribution, headers=admitted), 400, "attribution_absent", True
        )
        record = check(
            source.post(
                attribution,
                headers=admitted,
                json={
                    "consent": True,
                    "url": origin + "/?utm_source=qa&utm_medium=email",
                    "referrer": "",
                },
            )
        )
        if (
            not record.get("consented_at")
            or not record.get("first_touch")
            or not record.get("last_touch")
        ):
            raise ValueError(
                "attribution_probe_record_invalid: restore the verified consent and touch contract"
            )
        if check(source.get(attribution, headers=admitted), no_cookie=True) != record:
            raise ValueError(
                "attribution_probe_read_changed: preserve the server-verified record"
            )
        token = check(
            source.post(mint, headers=admitted, json={"audience": origin}),
            no_cookie=True,
        )["token"]
        check(
            destination.get(attribution, headers=admitted),
            400,
            "attribution_absent",
            True,
        )
        delivered = destination.post(redeem, headers=admitted, json={"token": token})
        if check(delivered) != record or "HttpOnly" not in delivered.headers.get(
            "set-cookie", ""
        ):
            raise ValueError(
                "attribution_probe_transfer_changed: preserve consented touches in the destination HttpOnly cookie"
            )
        if (
            check(destination.get(attribution, headers=admitted), no_cookie=True)
            != record
        ):
            raise ValueError(
                "attribution_probe_destination_invalid: restore verified destination-cookie reads"
            )
        check(
            destination.post(redeem, headers=admitted, json={"token": token}),
            400,
            "attribution_handoff_replayed",
            True,
        )
        check(
            destination.post(redeem, headers=admitted, json={"token": token + "x"}),
            400,
            "attribution_handoff_invalid",
            True,
        )
        for client in (source, destination):
            check(client.delete(attribution, headers=admitted))
            check(
                client.get(attribution, headers=admitted),
                400,
                "attribution_absent",
                True,
            )
    print(
        "attribution transfer passed: verified read, isolated cookie jars, one-time redemption, forgery refusal and revocation"
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
            else "attribution_probe_unavailable: restore deployed collector access and rerun the case"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
