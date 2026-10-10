"""Executable Python/browser parity, cookie and delivery contracts."""

import io
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from events_attribution import (
    capture_touch,
    update_attribution,
    get_attribution_props,
    sanitize_url,
    is_bot,
)
from events_cookie import AttributionCookie, COOKIE_NAME
from events_delivery import EventBatch
from events_attribution import RULES

HERE = Path(__file__).resolve().parent


def test_python_matches_browser_rules():
    # One shared corpus is evaluated by both languages, including priority collisions.
    visits = [
        ("?utm_medium=broadcast", "", "unassigned"),
        ("", "https://netflix.com", "referral"),
        ("", "https://www.google.co.uk/search", "organic_search"),
        ("", "https://docs.example.com", "direct"),
        ("", "https://example.com/", "direct"),
        ("", "https://accounts.google.com/", "direct"),
        ("", "https://accounts.youtube.com/", "direct"),
        ("", "https://login.microsoftonline.com/", "direct"),
        ("", "https://www.google.com/", "organic_search"),
        ("", "https://www.youtube.com/", "organic_video"),
        ("", "https://fakegoogle.com", "referral"),
        ("", "https://notchatgpt.com", "referral"),
        ("", "https://chatgpt.com", "ai_assistant"),
        ("", "https://perplexity.ai", "ai_assistant"),
        ("", "https://gemini.google.com", "ai_assistant"),
        ("", "https://copilot.microsoft.com", "ai_assistant"),
        ("?utm_source=chatgpt.com", "", "ai_assistant"),
        ("?utm_source=google&utm_medium=cpc", "", "paid_search"),
        ("?utm_source=x.com&utm_medium=cpc", "", "paid_social"),
        ("?utm_medium=email", "https://google.com", "organic_search"),
        ("?utm_medium=display", "https://google.com", "display"),
        ("?utm_medium=upload", "", "unassigned"),
        ("?utm_medium=lead_nurture", "", "unassigned"),
        ("?gclid=google", "", "paid_search"),
        ("?msclkid=microsoft", "https://bing.com", "paid_search"),
        ("?fbclid=facebook", "", "paid_social"),
        ("?li_fat_id=linkedin", "", "paid_social"),
        (
            "?utm_medium=organic&gclid=a&fbclid=b&msclkid=c&li_fat_id=d&utm_id=e&utm_source_platform=f",
            "",
            "paid_search",
        ),
    ]
    corpus = [
        {
            "url": "https://app.example.com/" + q,
            "referrer": r,
            "site": "example.com",
            "now": "2026-01-01T00:00:00Z",
        }
        for q, r, _ in visits
    ]
    js = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            "import {captureTouch} from './events_attribution.ts'; let s=''; for await(const x of process.stdin)s+=x; console.log(JSON.stringify(JSON.parse(s).map(v=>captureTouch(v.url,v.referrer,v.site,v.now))));",
        ],
        cwd=HERE,
        input=json.dumps(corpus),
        text=True,
        capture_output=True,
        check=True,
    )
    browser = json.loads(js.stdout)
    python = [
        capture_touch(v["url"], v["referrer"], v["site"], v["now"]) for v in corpus
    ]
    assert python == browser
    assert [t["acquisition_channel"] for t in python] == [v[2] for v in visits]
    assert [
        python[-1][k]
        for k in (
            "gclid",
            "fbclid",
            "msclkid",
            "li_fat_id",
            "utm_id",
            "utm_source_platform",
        )
    ] == list("abcdef")


def test_first_touch_never_overwritten_and_last_touch_updates():
    direct = capture_touch("https://example.com", "", "example.com", "first")
    first = update_attribution(None, direct, "visitor")
    organic = capture_touch(
        "https://example.com", "https://google.co.uk", "example.com", "second"
    )
    second = update_attribution(first, organic, "ignored")
    assert second["visitor_id"] == "visitor"
    assert second["first_touch"] == direct
    assert second["last_touch"] == organic
    assert update_attribution(second, direct, "ignored") == second
    assert get_attribution_props(second) == second
    assert get_attribution_props(None) == {}


def test_sign_in_and_own_domain_returns_keep_prior_touches():
    site = "example.com"
    landing = capture_touch(
        "https://www.example.com/", "https://www.google.com/", site, "first"
    )
    record = update_attribution(None, landing, "visitor")
    for hop in (
        "https://accounts.google.com/",
        "https://accounts.youtube.com/",
        "https://example.com/pricing",
    ):
        touch = capture_touch("https://app.example.com/", hop, site, "later")
        assert touch["referrer_domain"] is None
        assert touch["acquisition_channel"] == "direct"
        assert update_attribution(record, touch, "ignored") == record
    # A sign-in hop as the very first visit is a direct first touch.
    first = capture_touch(
        "https://app.example.com/", "https://accounts.google.com/", site, "first"
    )
    assert (
        update_attribution(None, first, "v")["first_touch"]["acquisition_channel"]
        == "direct"
    )


def test_server_cookie_persistence_and_integrity():
    cookie = AttributionCookie("s" * 32, "example.com")
    first, header = cookie.capture("", "https://example.com", "")
    assert all(
        flag in header for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Max-Age=")
    )
    second, _ = cookie.capture(header, "https://example.com", "https://google.com")
    assert first["visitor_id"] == second["visitor_id"]
    assert first["first_touch"] == second["first_touch"]
    assert second["last_touch"]["acquisition_channel"] == "organic_search"
    with pytest.warns(RuntimeWarning, match="attribution_cookie_reminted"):
        assert cookie.read(f"{COOKIE_NAME}=bad.bad") is None
    with pytest.raises(ValueError, match="attribution_site_mismatch"):
        cookie.capture("", "https://evil.com", "")
    # Python server cookie can be verified by the JS server with the same secret.
    js = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            "import {createAttributionCookie} from './events_cookie.ts'; let s=''; for await(const x of process.stdin)s+=x; console.log(JSON.stringify(await (await createAttributionCookie('s'.repeat(32),'example.com')).read(s)));",
        ],
        cwd=HERE,
        input=header,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(js.stdout) == first


def test_url_hygiene_and_bots():
    assert (
        sanitize_url(
            "https://user:password@example.com/?token=secret&EMAIL=private&tab=orders#token"
        )
        == "https://example.com/?tab=orders"
    )
    assert sanitize_url("javascript:alert(1)") is None
    assert is_bot("HeadlessChrome") and not is_bot("Mozilla/5.0")


def test_batches_requeue_network_failure_and_honor_429():
    clock = [100]
    calls = []

    def transport(request, timeout):
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            raise OSError("offline")
        raise HTTPError(request.full_url, 429, "busy", {"Retry-After": "30"}, None)

    batch = EventBatch(
        "https://example.com/api/events",
        "public",
        transport=transport,
        clock=lambda: clock[0],
    )
    batch.append({"event_id": "stable"})
    with pytest.warns(RuntimeWarning, match="batch_requeued"):
        batch.flush()
    batch.flush()
    assert len(calls) == 1
    clock[0] = 106
    with pytest.warns(RuntimeWarning, match="batch_requeued"):
        batch.flush()
    assert batch.queue == [{"event_id": "stable"}]
    assert batch.retry_at == 136
    assert calls[0] == calls[1]


@pytest.mark.parametrize("status", [400, 401, 403])
def test_batches_discard_permanent_refusals_with_named_recovery(status):
    calls = []

    def transport(request, timeout):
        calls.append(request)
        body = io.BytesIO(
            b'{"error":"publishable_key_invalid","recovery":"configure the current public key"}'
        )
        raise HTTPError(request.full_url, status, "refused", {}, body)

    batch = EventBatch("https://example.com/api/events", "public", transport=transport)
    batch.append({"event_id": "discard"})
    with pytest.warns(
        RuntimeWarning,
        match="batch_refused: publishable_key_invalid; configure the current public key",
    ):
        batch.flush()
    batch.flush()
    assert batch.queue == [] and len(calls) == 1 and batch.retry_at == 0
    assert calls[0].get_header("X-events-key") == "public"


def test_batch_capacity_preserves_retry_ids_under_concurrent_append():
    capacity = RULES["limits"]["queue_events"]

    def transport(request, timeout):
        for index in range(capacity):
            batch.append({"event_id": f"new-{index}"})
        raise HTTPError(request.full_url, 503, "busy", {}, None)

    batch = EventBatch(
        "https://example.com/api/events",
        "public",
        transport=transport,
        clock=lambda: 100,
    )
    batch.append({"event_id": "stable"})
    with pytest.warns(RuntimeWarning) as warnings:
        batch.flush()
    assert len(batch.queue) == capacity and batch.queue[0]["event_id"] == "stable"
    assert batch.retry_at == 105
    assert any("batch_queue_full" in str(w.message) for w in warnings)
    with pytest.warns(RuntimeWarning, match="batch_queue_full"):
        batch.append({"event_id": "latest"})
    assert len(batch.queue) == capacity and batch.queue[-1]["event_id"] == "latest"
    with pytest.raises(ValueError, match="publishable_key_required"):
        EventBatch("https://example.com/api/events", "")


def test_cookie_rotation_and_domain_normalization_match_browser():
    old = AttributionCookie("s" * 32, "example.com")
    original, header = old.capture("", "https://example.com", "")
    current = AttributionCookie("t" * 32, "WWW.EXAMPLE.COM.")
    with pytest.warns(RuntimeWarning, match="attribution_cookie_reminted"):
        renewed, new_header = current.capture(
            header, "https://APP.EXAMPLE.COM./?gclid=paid", ""
        )
    assert renewed["visitor_id"] != original["visitor_id"]
    assert renewed["first_touch"]["acquisition_channel"] == "paid_search"
    assert current.read(new_header) == renewed
    urls = [
        "https://APP.EXAMPLE.COM./?gclid=paid",
        "https://www.example.com",
        "https://notexample.com",
        "https://example.com.evil.com",
    ]
    expected = [True, True, False, False]
    for url, accepted in zip(urls, expected):
        if accepted:
            assert current.capture("", url, "")[0]["visitor_id"]
        else:
            with pytest.raises(ValueError, match="attribution_site_mismatch"):
                current.capture("", url, "")
    script = """
      import {createAttributionCookie} from './events_cookie.ts';
      let input=''; for await(const value of process.stdin) input+=value;
      const {urls, header, visitor}=JSON.parse(input);
      const cookie=await createAttributionCookie('t'.repeat(32),'WWW.EXAMPLE.COM.');
      const accepted=[];
      for(const url of urls) {
        try { await cookie.capture('',url,'',true); accepted.push(true); }
        catch(error) { if(!error.message.includes('attribution_site_mismatch')) throw error; accepted.push(false); }
      }
      const renewed=await cookie.capture(header,urls[0],'',true);
      console.log(JSON.stringify({accepted, rotated:renewed.record.visitor_id!==visitor,
        channel:renewed.record.first_touch.acquisition_channel, verified:!!await cookie.read(renewed.setCookie)}));
    """
    js = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=HERE,
        input=json.dumps(
            {"urls": urls, "header": header, "visitor": original["visitor_id"]}
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(js.stdout) == {
        "accepted": expected,
        "rotated": True,
        "channel": "paid_search",
        "verified": True,
    }
