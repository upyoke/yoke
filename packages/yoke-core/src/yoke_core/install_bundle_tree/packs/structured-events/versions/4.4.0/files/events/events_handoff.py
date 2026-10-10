"""Signed attribution transfer with destination binding and durable one-time redemption."""

import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlsplit

from events_cookie import _decode, _encode, validate_record

HANDOFF_SECONDS = 120
HANDOFF_PURPOSE = "attribution_handoff"


def handoff_origin(value):
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise ValueError()
        host = parts.hostname.encode("idna").decode().lower()
        host = f"[{host}]" if ":" in host else host
        port = parts.port
        return f"https://{host}" + (f":{port}" if port and port != 443 else "")
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(
            "attribution_handoff_origin_invalid: supply an exact HTTPS destination origin without a path"
        ) from error


class AttributionHandoff:
    def __init__(self, cookie):
        self.cookie = cookie

    def mint(self, cookie_header, audience):
        record = self.cookie.read_verified(cookie_header)
        audience = handoff_origin(audience)
        expires = int(time.time()) + HANDOFF_SECONDS
        payload = _encode(
            json.dumps(
                {
                    "purpose": HANDOFF_PURPOSE,
                    "audience": audience,
                    "expires": expires,
                    "nonce": str(uuid.uuid4()),
                    "record": record,
                },
                separators=(",", ":"),
            ).encode()
        )
        signature = _encode(
            hmac.new(
                self.cookie.secret,
                (HANDOFF_PURPOSE + ":" + payload).encode(),
                hashlib.sha256,
            ).digest()
        )
        return {"token": f"{payload}.{signature}", "expires_at": expires}

    def redeem(self, token, audience, consume):
        """consume(nonce, expires) must atomically insert once in durable storage.

        Return true for the first insertion, false for replay; storage errors must
        raise. Never use an in-memory set or disposable event rows.
        """
        audience = handoff_origin(audience)
        try:
            if not isinstance(token, str) or len(token) > 8192:
                raise ValueError()
            payload, signature = token.split(".")
            expected = hmac.new(
                self.cookie.secret,
                (HANDOFF_PURPOSE + ":" + payload).encode(),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(expected, _decode(signature)):
                raise ValueError()
            decoded = json.loads(_decode(payload))
            if decoded["purpose"] != HANDOFF_PURPOSE:
                raise ValueError()
            uuid.UUID(decoded["nonce"])
            if not isinstance(decoded["expires"], int):
                raise ValueError()
            record = validate_record(decoded["record"])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError(
                "attribution_handoff_invalid: restart sign-in from the source origin"
            ) from error
        if decoded["expires"] <= time.time():
            raise ValueError(
                "attribution_handoff_expired: restart sign-in to mint a fresh token"
            )
        if decoded["audience"] != audience:
            raise ValueError(
                "attribution_handoff_audience_mismatch: redeem at the exact destination origin used when minting"
            )
        header = self.cookie.write(record)
        if not consume(decoded["nonce"], decoded["expires"]):
            raise ValueError(
                "attribution_handoff_replayed: restart sign-in to mint a fresh one-time token"
            )
        return record, header
