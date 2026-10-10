"""Frontend analytics: exact origin/key, shared rate budget, named refusals.

Page views are anonymous unless the request carries the viewer's credential
(bearer or web session); then the row carries that actor. Anonymous views
carry only the browser's visitor id, which ties them to an actor at query
time once that browser signs in (:mod:`yoke_core.domain.actor_visitor_links`).
"""

import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from yoke_core.api.frontend_events_config import (
    ATTRIBUTION_PATH,
    CONFIG_PATH,
    EVENTS_PATH,
    HANDOFF_PATH,
    REDEEM_PATH,
    attribution_cookie,
    collector_origin,
    cookie_input,
    cookie_output,
)
from yoke_core.api.http_auth import authenticate_request
from yoke_core.api.observability_otel import environment_name
from yoke_core.api.web_session_auth import authenticate_web_session
from yoke_core.domain import db_helpers
from yoke_core.domain.frontend_collector_refusals import record_refusal
from yoke_core.domain.frontend_events_storage import (
    admit_client,
    consume_attribution_handoff,
    read_collector_identity,
    write_frontend_events,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def recorded(request, response, reason):
    """Record the refusal after the response is sent; telemetry never delays it."""
    response.background = BackgroundTask(
        record_refusal,
        reason=reason,
        status=response.status_code,
        route=request.url.path,
        origin=request.headers.get("origin", ""),
        host=request.url.netloc,
    )
    return response


def refusal(request, status, error, recovery, **headers):
    response = JSONResponse(
        {"error": error, "recovery": recovery}, status_code=status, headers=headers
    )
    return recorded(request, response, error)


def refused_authorization(request, response):
    try:
        reason = json.loads(response.body).get("error") or "unauthorized"
    except (ValueError, AttributeError):
        reason = "unauthorized"
    return recorded(request, response, str(reason))


def admission(request):
    origin = collector_origin(request)
    if request.headers.get("origin") != origin:
        return refusal(
            request,
            403,
            "origin_not_allowed",
            "Send from the exact serving origin; preserve Host or set "
            "X-Forwarded-Host at the proxy, and set "
            "YOKE_API_TRUSTED_PROXIES to the TLS proxy IPs/CIDRs, then restart "
            "with yoke self-host init --dir PATH --protect-existing --start.",
        )
    org_id, key, _ = read_collector_identity()
    if request.headers.get("x-events-key") != key:
        return refusal(
            request,
            401,
            "publishable_key_invalid",
            "Reload /api/events/config and configure the returned publishableKey.",
        )
    with db_helpers.connect() as conn:
        delay = admit_client(
            conn,
            org_id=org_id,
            client=request.client.host if request.client else "unknown",
        )
    if delay:
        return refusal(
            request,
            429,
            "rate_limited",
            "Retry the same event ids after Retry-After.",
            **{"Retry-After": str(delay)},
        )
    return org_id


async def body_json(request):
    from yoke_core.frontend_events.events_attribution import RULES

    if (
        not request.headers.get("content-type", "")
        .lower()
        .startswith("application/json")
    ):
        raise ValueError("content_type_invalid: send application/json")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > RULES["limits"]["request_bytes"]:
            raise ValueError("payload_too_large: reduce the request below 512 KB")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, UnicodeError) as error:
        raise ValueError("json_invalid: send a valid JSON object") from error


def validated_events(body, request):
    from yoke_core.frontend_events.events_attribution import (
        RULES,
        sanitize_path,
        sanitize_url,
    )
    from yoke_core.frontend_events.events_device import device_props

    events = body.get("events") if isinstance(body, dict) else None
    if (
        not isinstance(events, list)
        or not 1 <= len(events) <= RULES["limits"]["batch_size"]
    ):
        raise ValueError("events_invalid: send 1..50 frontend analytics envelopes")
    device = device_props(request.headers)
    for event in events:
        if not isinstance(event, dict) or any(
            not isinstance(event.get(k), str) or not event[k]
            for k in (
                "event_id",
                "event_name",
                "event_kind",
                "event_type",
                "event_time",
                "session_id",
                "service",
                "project",
            )
        ):
            raise ValueError(
                "envelope_invalid: use the frontend emitter's complete envelope"
            )
        try:
            UUID(event["event_id"])
            datetime.fromisoformat(event["event_time"].replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(
                "envelope_invalid: use a UUID event_id and ISO event_time"
            ) from error
        if event.get("source_type") != "frontend" or event["event_kind"] != "analytics":
            raise ValueError(
                "envelope_invalid: anonymous collection admits frontend analytics only"
            )
        if (
            len(json.dumps(event, ensure_ascii=False).encode())
            > RULES["limits"]["envelope_bytes"]
        ):
            raise ValueError("event_too_large: reduce the envelope below 64 KB")
        for key in ("page_url", "referrer"):
            if event.get(key) is not None and not isinstance(event[key], str):
                raise ValueError(
                    "envelope_invalid: page_url and referrer must be strings or null"
                )
            event[key] = sanitize_url(event.get(key) or "")
        if event.get("page_path") is not None:
            if not isinstance(event["page_path"], str):
                raise ValueError("envelope_invalid: page_path must be a string or null")
            event["page_path"] = sanitize_path(event["page_path"])
        event.update(device)
    return events


def viewer_actor_id(request, auth):
    """The signed-in viewer: a credential, else the serving host's own viewer.

    A host that admits its browser by other means (the Local view's per-run
    token) names that viewer in ``request.state.viewer_actor_id``.
    """
    if auth:
        return auth.actor_id
    return getattr(request.state, "viewer_actor_id", None)


def diagnosed(request, error):
    reason, _, recovery = str(error).partition(":")
    return refusal(
        request,
        413 if reason in ("event_too_large", "payload_too_large") else 400,
        reason,
        recovery.strip() or "Check collector input and retry.",
    )


@router.get(CONFIG_PATH)
def configuration(request: Request):
    try:
        collector_origin(request)
        _, key, _ = read_collector_identity()
        return JSONResponse(
            {"publishableKey": key}, headers={"Cache-Control": "no-store"}
        )
    except ValueError as error:
        return diagnosed(request, error)
    except Exception:
        _log.exception("collector_unavailable: restore the boot-converged database")
        return refusal(
            request,
            503,
            "collector_unavailable",
            "Restore the collector database and reload.",
        )


@router.post(EVENTS_PATH)
async def collect(request: Request):
    try:
        admitted = await run_in_threadpool(admission, request)
        if isinstance(admitted, JSONResponse):
            return admitted
        events = validated_events(await body_json(request), request)
        if request.headers.get("authorization"):
            auth = await run_in_threadpool(authenticate_request, request)
            if isinstance(auth, JSONResponse):
                return refused_authorization(request, auth)
        else:
            auth = await run_in_threadpool(authenticate_web_session, request)
        await run_in_threadpool(
            write_frontend_events,
            events,
            org_id=admitted,
            environment=environment_name(),
            actor_id=viewer_actor_id(request, auth),
        )
        return JSONResponse({"accepted": len(events)})
    except ValueError as error:
        return diagnosed(request, error)
    except Exception:
        _log.exception("collector_unavailable: restore the limiter or event sink")
        return refusal(
            request,
            503,
            "collector_unavailable",
            "Restore the limiter or sink, then retry the same event ids.",
        )


@router.api_route(ATTRIBUTION_PATH, methods=["GET", "POST"])
async def attribution(request: Request):
    try:
        admitted = await run_in_threadpool(admission, request)
        if isinstance(admitted, JSONResponse):
            return admitted
        cookie = await run_in_threadpool(attribution_cookie, request)
        if request.method == "GET":
            record = cookie.read_verified(cookie_input(request))
            return JSONResponse(record, headers={"Cache-Control": "no-store"})
        body = await body_json(request)
        if not isinstance(body, dict) or any(
            not isinstance(body.get(k), str) for k in ("url", "referrer")
        ):
            raise ValueError("attribution_input_invalid: send url and referrer strings")
        record, header = cookie.capture(
            cookie_input(request), body["url"], body["referrer"]
        )
        return JSONResponse(
            record,
            headers={
                "Set-Cookie": cookie_output(request, header),
                "Cache-Control": "no-store",
            },
        )
    except ValueError as error:
        response = diagnosed(request, error)
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception:
        _log.exception("attribution_unavailable: restore the limiter or signing key")
        return refusal(
            request,
            503,
            "attribution_unavailable",
            "Restore collector storage and retry attribution capture.",
        )


@router.post(HANDOFF_PATH)
@router.post(REDEEM_PATH)
async def attribution_handoff(request: Request):
    from yoke_core.frontend_events.events_handoff import (
        AttributionHandoff,
        handoff_origin,
    )

    try:
        admitted = await run_in_threadpool(admission, request)
        if isinstance(admitted, JSONResponse):
            return admitted
        cookie = await run_in_threadpool(attribution_cookie, request)
        handoff_origin(collector_origin(request))
        handoff = AttributionHandoff(cookie)
        body = await body_json(request)
        if not isinstance(body, dict):
            raise ValueError("attribution_input_invalid: send a JSON object")
        headers = {"Cache-Control": "no-store"}
        if request.url.path == REDEEM_PATH:

            def consume(nonce, expires):
                return consume_attribution_handoff(admitted, nonce, expires)

            record, header = await run_in_threadpool(
                handoff.redeem, body.get("token"), collector_origin(request), consume
            )
            headers["Set-Cookie"] = cookie_output(request, header)
        else:
            record = handoff.mint(cookie_input(request), body.get("audience"))
        return JSONResponse(record, headers=headers)
    except ValueError as error:
        response = diagnosed(request, error)
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception:
        _log.exception("attribution_handoff_unavailable: restore durable nonce storage")
        return refusal(
            request,
            503,
            "attribution_handoff_unavailable",
            "Restore collector signing identity and durable nonce storage, then restart sign-in.",
            **{"Cache-Control": "no-store"},
        )
