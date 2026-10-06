"""Verified reads and cross-language single-use attribution transfers."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from events_cookie import AttributionCookie, COOKIE_NAME
from events_handoff import AttributionHandoff, HANDOFF_SECONDS

DESTINATION = "https://app.example.com"
HERE = Path(__file__).resolve().parent


@pytest.fixture
def consented():
    cookie = AttributionCookie("s" * 32, "example.com")
    record, header = cookie.capture(
        "", "https://example.com/?utm_source=email", "", consent=True
    )
    return cookie, record, header


def test_verified_read_never_remints_and_preserves_consent(consented):
    cookie, record, header = consented
    assert cookie.read_verified(header) == record
    assert record["consented_at"]
    with pytest.raises(ValueError, match="attribution_absent"):
        cookie.read_verified("")
    with pytest.raises(ValueError, match="attribution_invalid"):
        cookie.read_verified(f"{COOKIE_NAME}=forged.payload")
    later, _ = cookie.capture(
        header, "https://example.com/?gclid=paid", "", consent=True
    )
    assert later["consented_at"] == record["consented_at"]


def test_handoff_redeems_once_and_binds_destination(consented):
    cookie, record, header = consented
    handoff = AttributionHandoff(cookie)
    token = handoff.mint(header, DESTINATION)["token"]
    with pytest.raises(ValueError, match="attribution_invalid"):
        cookie.read_verified(f"{COOKIE_NAME}={token}")
    used = set()

    def consume(nonce, expires):
        if nonce in used:
            return False
        used.add(nonce)
        return True

    with pytest.raises(ValueError, match="audience_mismatch"):
        handoff.redeem(token, "https://other.example.com", consume)
    assert not used
    redeemed, destination_cookie = handoff.redeem(token, DESTINATION, consume)
    assert redeemed == record == cookie.read_verified(destination_cookie)
    with pytest.raises(ValueError, match="replayed"):
        handoff.redeem(token, DESTINATION, consume)


def test_handoff_expiry_forgery_and_absent_consent(consented, monkeypatch):
    cookie, _, header = consented
    handoff = AttributionHandoff(cookie)
    with pytest.raises(ValueError, match="attribution_absent"):
        handoff.mint("", DESTINATION)
    for audience in (
        "http://app.example.com",
        DESTINATION + "/path",
        "https://user@app.example.com",
    ):
        with pytest.raises(ValueError, match="origin_invalid"):
            handoff.mint(header, audience)
    monkeypatch.setattr("events_handoff.time.time", lambda: 100)
    token = handoff.mint(header, DESTINATION)["token"]

    def forbidden(*args):
        pytest.fail("invalid token must never consume durable state")

    for forged in ("garbage", token + "x", token.split(".")[0] + ".bad", None):
        with pytest.raises(ValueError, match="handoff_invalid"):
            handoff.redeem(forged, DESTINATION, forbidden)
    monkeypatch.setattr("events_handoff.time.time", lambda: 100 + HANDOFF_SECONDS)
    with pytest.raises(ValueError, match="expired"):
        handoff.redeem(token, DESTINATION, forbidden)


def test_python_typescript_cookie_and_handoff_wire_parity(consented):
    cookie, record, header = consented
    token = AttributionHandoff(cookie).mint(header, DESTINATION)["token"]
    script = """
      import {createAttributionCookie} from './events_cookie.ts';
      import {createAttributionHandoff, HANDOFF_SECONDS} from './events_handoff.ts';
      let input=''; for await (const x of process.stdin) input+=x;
      const {header, token, audience}=JSON.parse(input);
      const cookie=await createAttributionCookie('s'.repeat(32),'example.com');
      const handoff=await createAttributionHandoff('s'.repeat(32),'example.com');
      const used=new Set();
      const consume=async nonce=>{if(used.has(nonce))return false;used.add(nonce);return true;};
      const redeemed=await handoff.redeem(token,audience,consume);
      const reasons=[];
      for(const [value,target] of [[token,audience],[token,'https://other.example.com'],[token+'x',audience]]) {
        try { await handoff.redeem(value,target,consume); }
        catch(error) { reasons.push(error.message.split(':')[0]); }
      }
      const minted=await handoff.mint(header,audience);
      const now=Date.now;
      Date.now=()=>now()+HANDOFF_SECONDS*1000;
      try { await handoff.redeem(minted.token,audience,consume); }
      catch(error) { reasons.push(error.message.split(':')[0]); }
      Date.now=now;
      console.log(JSON.stringify({record:redeemed.record, verified:await cookie.readVerified(redeemed.setCookie), token:minted.token, reasons}));
    """
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=HERE,
        input=json.dumps({"header": header, "token": token, "audience": DESTINATION}),
        text=True,
        capture_output=True,
        check=True,
    )
    js = json.loads(result.stdout)
    assert js["record"] == js["verified"] == record
    assert js["reasons"] == [
        "attribution_handoff_replayed",
        "attribution_handoff_audience_mismatch",
        "attribution_handoff_invalid",
        "attribution_handoff_expired",
    ]
    assert (
        AttributionHandoff(cookie).redeem(js["token"], DESTINATION, lambda *args: True)[
            0
        ]
        == record
    )
