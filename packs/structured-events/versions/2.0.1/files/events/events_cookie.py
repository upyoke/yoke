"""HTTP-neutral signed attribution cookie for Python collectors; HTTPS required."""

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
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


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

    def read(self, cookie):
        try:
            parsed = SimpleCookie(cookie)
            if COOKIE_NAME not in parsed:
                return None
            payload, signature = parsed[COOKIE_NAME].value.split(".")
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _decode(signature)):
                raise ValueError()
            decoded = json.loads(_decode(payload))
            if decoded["expires"] <= time.time():
                return None
            record = decoded["record"]
            if (
                not record["visitor_id"]
                or not record["first_touch"]
                or not record["last_touch"]
            ):
                raise ValueError()
            return record
        except Exception:
            warnings.warn(
                "attribution_cookie_reminted: invalid or rotated signature; discard old identity and capture with the current secret",
                RuntimeWarning,
                stacklevel=2,
            )
            return None

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
        touch = capture_touch(url, referrer, self.site_domain, now)
        record = update_attribution(self.read(cookie), touch, str(uuid.uuid4()))
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
        return (
            record,
            f"{COOKIE_NAME}={value}; Max-Age={COOKIE_SECONDS}; Path=/; Secure; HttpOnly; SameSite=Lax",
        )
