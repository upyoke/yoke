# Generated from the installed structured-events Pack; run build_frontend_events.
"""HTTP-neutral signed attribution cookie; HTTPS required."""

import base64
import hashlib
import hmac
import json
import uuid
import warnings
from datetime import timedelta
from .events_timestamps import format_instant, parse_instant, utc_now
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from .events_attribution import RULES, capture_touch, domain_matches, update_attribution

COOKIE_NAME = RULES["limits"]["cookie_name"]
COOKIE_SECONDS = RULES["limits"]["cookie_seconds"]


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value):
    return base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )


RECORD_KEYS = ("visitor_id", "first_touch", "last_touch")


def validate_record(record):
    """Return the attribution record's own fields; any other key is dropped."""
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("visitor_id"), str)
        or not record["visitor_id"]
        or any(
            not isinstance(record.get(k), dict) or not record[k]
            for k in ("first_touch", "last_touch")
        )
    ):
        raise ValueError("attribution_invalid: capture attribution again")
    for key in ("first_touch", "last_touch"):
        value = record[key].get("captured_at")
        if not isinstance(value, str) or format_instant(value) != value:
            raise ValueError(
                "attribution_invalid: capture attribution again with canonical UTC instants"
            )
    return {k: record[k] for k in RECORD_KEYS}


class AttributionCookie:
    def __init__(self, secret, site_domain):
        if len(secret) < RULES["limits"]["signing_secret_chars"] or not site_domain:
            raise ValueError(
                "attribution_configuration_invalid: supply a private 32-character signing secret and own site domain"
            )
        self.secret = secret.encode()
        self.site_domain = site_domain

    def read_verified(self, cookie):
        """Read without minting, clearing, or modifying a cookie."""
        try:
            parsed = SimpleCookie(cookie)
            if COOKIE_NAME not in parsed:
                if COOKIE_NAME in cookie:
                    raise ValueError()
                raise ValueError("attribution_absent: capture attribution first")
            payload, signature = parsed[COOKIE_NAME].value.split(".")
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _decode(signature)):
                raise ValueError()
            decoded = json.loads(_decode(payload))
            if (
                not isinstance(decoded.get("expires"), str)
                or format_instant(decoded["expires"]) != decoded["expires"]
                or parse_instant(decoded["expires"]) <= utc_now()
            ):
                raise ValueError()
            return validate_record(decoded["record"])
        except ValueError as error:
            if str(error).startswith("attribution_absent:"):
                raise
            raise ValueError(
                "attribution_invalid: capture attribution again"
            ) from error
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(
                "attribution_invalid: capture attribution again"
            ) from error

    def read(self, cookie):
        try:
            return self.read_verified(cookie)
        except ValueError as error:
            if not str(error).startswith("attribution_absent:"):
                warnings.warn(
                    "attribution_cookie_reminted: invalid or rotated signature; discard old identity and capture with the current secret",
                    RuntimeWarning,
                    stacklevel=2,
                )
            return None

    def write(self, record):
        """Serialize a server-verified record."""
        record = validate_record(record)
        payload = _encode(
            json.dumps(
                {
                    "record": record,
                    "expires": format_instant(
                        utc_now() + timedelta(seconds=COOKIE_SECONDS)
                    ),
                },
                separators=(",", ":"),
            ).encode()
        )
        signature = _encode(
            hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
        )
        value = f"{payload}.{signature}"
        if len(value) > RULES["limits"]["cookie_value_chars"]:
            raise ValueError(
                "attribution_cookie_too_large: shorten campaign values or use an atomic server record keyed by visitor_id"
            )
        return f"{COOKIE_NAME}={value}; Max-Age={COOKIE_SECONDS}; Path=/; Secure; HttpOnly; SameSite=Lax"

    def capture(self, cookie, url, referrer):
        if not domain_matches(urlsplit(url).hostname or "", self.site_domain):
            raise ValueError(
                "attribution_site_mismatch: send a URL belonging to the configured site domain"
            )
        now = format_instant(utc_now())
        existing = self.read(cookie)
        touch = capture_touch(url, referrer, self.site_domain, now)
        record = update_attribution(existing, touch, str(uuid.uuid4()))
        return record, self.write(record)
