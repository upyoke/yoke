"""HTTP-neutral signed, consented attribution cookie; HTTPS required."""

import base64
import hashlib
import hmac
import json
import time
import uuid
import warnings
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from events_attribution import RULES, capture_touch, domain_matches, update_attribution

COOKIE_NAME = RULES["limits"]["cookie_name"]
COOKIE_SECONDS = RULES["limits"]["cookie_seconds"]


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value):
    return base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )


def validate_record(record):
    if (
        not isinstance(record, dict)
        or any(
            not isinstance(record.get(k), str) or not record[k]
            for k in ("visitor_id", "consented_at")
        )
        or any(
            not isinstance(record.get(k), dict) or not record[k]
            for k in ("first_touch", "last_touch")
        )
    ):
        raise ValueError(
            "attribution_invalid: obtain consent and capture attribution again"
        )
    try:
        consented = datetime.fromisoformat(
            record["consented_at"].replace("Z", "+00:00")
        )
        if consented.tzinfo is None:
            raise ValueError()
    except ValueError as error:
        raise ValueError(
            "attribution_invalid: capture a valid consent timestamp"
        ) from error
    return record


class AttributionCookie:
    def __init__(self, secret, site_domain):
        if len(secret) < RULES["limits"]["signing_secret_chars"] or not site_domain:
            raise ValueError(
                "attribution_configuration_invalid: supply a private 32-character signing secret and own site domain"
            )
        self.secret = secret.encode()
        self.site_domain = site_domain

    @property
    def clear(self):
        return f"{COOKIE_NAME}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax"

    def read_verified(self, cookie):
        """Read without minting, clearing, or modifying a cookie."""
        try:
            parsed = SimpleCookie(cookie)
            if COOKIE_NAME not in parsed:
                if COOKIE_NAME in cookie:
                    raise ValueError()
                raise ValueError(
                    "attribution_absent: obtain consent and capture attribution first"
                )
            payload, signature = parsed[COOKIE_NAME].value.split(".")
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _decode(signature)):
                raise ValueError()
            decoded = json.loads(_decode(payload))
            if (
                not isinstance(decoded.get("expires"), (int, float))
                or decoded["expires"] <= time.time()
            ):
                raise ValueError()
            return validate_record(decoded["record"])
        except ValueError as error:
            if str(error).startswith("attribution_absent:"):
                raise
            raise ValueError(
                "attribution_invalid: obtain consent and capture attribution again"
            ) from error
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(
                "attribution_invalid: obtain consent and capture attribution again"
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
        """Serialize a server-verified record, including its original consent."""
        validate_record(record)
        payload = _encode(
            json.dumps(
                {"record": record, "expires": int(time.time()) + COOKIE_SECONDS},
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

    def capture(self, cookie, url, referrer, *, consent):
        if not consent:
            raise ValueError(
                "consent_required: obtain consent before attribution capture"
            )
        if not domain_matches(urlsplit(url).hostname or "", self.site_domain):
            raise ValueError(
                "attribution_site_mismatch: send a URL belonging to the configured site domain"
            )
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        existing = self.read(cookie)
        touch = capture_touch(url, referrer, self.site_domain, now)
        record = update_attribution(existing, touch, str(uuid.uuid4()))
        record["consented_at"] = existing["consented_at"] if existing else now
        return record, self.write(record)
