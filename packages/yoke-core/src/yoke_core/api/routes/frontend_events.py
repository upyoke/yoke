"""Anonymous frontend analytics: exact origin/key, shared rate budget, named refusals."""

import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from yoke_core.api.frontend_events_config import (
    ATTRIBUTION_PATH,
    CONFIG_PATH,
    EVENTS_PATH,
    attribution_cookie,
    collector_origin,
    cookie_input,
    cookie_output,
)
from yoke_core.api.http_auth import authenticate_request
from yoke_core.api.web_session_auth import authenticate_web_session
from yoke_core.domain import db_helpers
from yoke_core.domain.frontend_events_storage import (
    admit_client,
    read_collector_identity,
    write_frontend_events,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def refusal(status, error, recovery, **headers):
    return JSONResponse(
        {"error": error, "recovery": recovery}, status_code=status, headers=headers
    )


def admission(request):
    origin = collector_origin(request)
    if request.headers.get("origin") != origin:
        return refusal(
            403,
            "origin_not_allowed",
            "Send from the exact serving origin; preserve Host and set "
            "YOKE_API_TRUSTED_PROXIES to the TLS proxy IPs/CIDRs, then restart "
            "with yoke self-host init --dir PATH --protect-existing --start.",
        )
    org_id, key, _ = read_collector_identity()
    if request.headers.get("x-events-key") != key:
        return refusal(
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
    from yoke_core.frontend_events.events_attribution import RULES, is_bot, sanitize_url

    events = body.get("events") if isinstance(body, dict) else None
    if (
        not isinstance(events, list)
        or not 1 <= len(events) <= RULES["limits"]["batch_size"]
    ):
        raise ValueError("events_invalid: send 1..50 frontend analytics envelopes")
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
        event["is_bot"] = is_bot(request.headers.get("user-agent", ""))
    return events


def diagnosed(error):
    reason, _, recovery = str(error).partition(":")
    return refusal(
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
        return diagnosed(error)
    except Exception:
        _log.exception("collector_unavailable: restore the boot-converged database")
        return refusal(
            503, "collector_unavailable", "Restore the collector database and reload."
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
                return auth
        else:
            auth = await run_in_threadpool(authenticate_web_session, request)
        await run_in_threadpool(
            write_frontend_events,
            events,
            org_id=admitted,
            actor_id=auth.actor_id if auth else None,
        )
        return JSONResponse({"accepted": len(events)})
    except ValueError as error:
        return diagnosed(error)
    except Exception:
        _log.exception("collector_unavailable: restore the limiter or event sink")
        return refusal(
            503,
            "collector_unavailable",
            "Restore the limiter or sink, then retry the same event ids.",
        )


@router.api_route(ATTRIBUTION_PATH, methods=["POST", "DELETE"])
async def attribution(request: Request):
    try:
        admitted = await run_in_threadpool(admission, request)
        if isinstance(admitted, JSONResponse):
            return admitted
        cookie = await run_in_threadpool(attribution_cookie, request)
        if request.method == "DELETE":
            record, header = {"cleared": True}, cookie.clear
        else:
            body = await body_json(request)
            if not isinstance(body, dict) or body.get("consent") is not True:
                return refusal(
                    403,
                    "consent_required",
                    "Obtain analytics consent before attribution capture.",
                )
            if any(not isinstance(body.get(k), str) for k in ("url", "referrer")):
                raise ValueError(
                    "attribution_input_invalid: send url and referrer strings"
                )
            record, header = cookie.capture(
                cookie_input(request), body["url"], body["referrer"], consent=True
            )
        return JSONResponse(
            record,
            headers={
                "Set-Cookie": cookie_output(request, header),
                "Cache-Control": "no-store",
            },
        )
    except ValueError as error:
        return diagnosed(error)
    except Exception:
        _log.exception("attribution_unavailable: restore the limiter or signing key")
        return refusal(
            503,
            "attribution_unavailable",
            "Restore collector storage and retry consent capture.",
        )
