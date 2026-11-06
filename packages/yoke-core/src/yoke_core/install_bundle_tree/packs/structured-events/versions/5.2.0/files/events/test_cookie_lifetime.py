"""Signed expiry and rolling renewal agree across the two server implementations."""

import base64
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import events_cookie
from events_timestamps import parse_instant, utc_now


def payload(header):
    value = header.split("=", 1)[1].split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


def test_signed_lifetime_and_direct_renewal_upgrade_old_cookie(monkeypatch):
    now = utc_now()
    monkeypatch.setattr(events_cookie, "utc_now", lambda: now)
    cookie = events_cookie.AttributionCookie("s" * 32, "example.com")
    monkeypatch.setattr(events_cookie, "COOKIE_SECONDS", 30 * 86400)
    original, legacy = cookie.capture("", "https://example.com", "")
    monkeypatch.setattr(events_cookie, "COOKIE_SECONDS", 400 * 86400)
    assert parse_instant(payload(legacy)["expires"]) == now + timedelta(days=30)
    now += timedelta(days=1)
    assert cookie.read_verified(legacy) == original
    for referrer in ("", "https://example.com/other"):
        renewed, header = cookie.capture(legacy, "https://example.com", referrer)
        assert renewed == original
        assert "Max-Age=34560000; Path=/; Secure; HttpOnly; SameSite=Lax" in header
        assert parse_instant(payload(header)["expires"]) == now + timedelta(days=400)
        legacy = header
        now += timedelta(days=31)
        assert cookie.read_verified(header) == original
    script = """
      import assert from 'node:assert/strict';
      import {createAttributionCookie} from './events_cookie.ts';
      let input=''; for await (const chunk of process.stdin) input+=chunk;
      const {legacy, original, start}=JSON.parse(input);
      let now=start; Date.now=()=>now;
      const cookie=await createAttributionCookie('s'.repeat(32),'example.com');
      const decode=h=>JSON.parse(Buffer.from(h.split('=')[1].split('.')[0],'base64url'));
      assert.deepEqual(await cookie.readVerified(legacy),original);
      let previous=legacy;
      for (const referrer of ['', 'https://example.com/other']) {
        const result=await cookie.capture(previous,'https://example.com',referrer);
        assert.deepEqual(result.record,original);
        assert.ok(result.setCookie.includes('Max-Age=34560000; Path=/; Secure; HttpOnly; SameSite=Lax'));
        assert.equal(Date.parse(decode(result.setCookie).expires),now+400*86400000);
        assert.ok(Date.parse(decode(result.setCookie).expires)>Date.parse(decode(previous).expires));
        now+=31*86400000;
        assert.deepEqual(await cookie.readVerified(result.setCookie),original);
        previous=result.setCookie;
      }
    """
    # Mint a still-valid old-lifetime cookie for the TypeScript upgrade path too.
    monkeypatch.setattr(events_cookie, "COOKIE_SECONDS", 30 * 86400)
    legacy = cookie.write(original)
    subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parent,
        input=json.dumps(
            {
                "legacy": legacy,
                "original": original,
                "start": int((now + timedelta(days=1)).timestamp() * 1000),
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
