"""Executable Python/browser parity, consent, cookie and delivery contracts."""

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

HERE = Path(__file__).resolve().parent


def test_python_matches_browser_rules():
    # One shared corpus is evaluated by both languages, including priority collisions.
    visits = [
        ("?utm_medium=broadcast", "", "unassigned"),
        ("", "https://netflix.com", "referral"),
        ("", "https://www.google.co.uk/search", "organic_search"),
        ("", "https://docs.example.com", "direct"),
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
        (
            "?utm_medium=organic&gclid=a&fbclid=b&msclkid=c&li_fat_id=d&utm_id=e&utm_source_platform=f",
            "",
            "organic_search",
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
    assert get_attribution_props(second, consent=False) == {}


def test_server_cookie_consent_persistence_and_integrity():
    cookie = AttributionCookie("s" * 32, "example.com")
    with pytest.raises(ValueError, match="consent_required"):
        cookie.capture("", "https://example.com", "", consent=False)
    first, header = cookie.capture("", "https://example.com", "", consent=True)
    assert all(
        flag in header for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Max-Age=")
    )
    second, _ = cookie.capture(
        header, "https://example.com", "https://google.com", consent=True
    )
    assert first["visitor_id"] == second["visitor_id"]
    assert first["first_touch"] == second["first_touch"]
    assert second["last_touch"]["acquisition_channel"] == "organic_search"
    with pytest.raises(ValueError, match="attribution_cookie_invalid"):
        cookie.read(f"{COOKIE_NAME}=bad.bad")
    assert "Max-Age=0" in cookie.clear
    with pytest.raises(ValueError, match="attribution_site_mismatch"):
        cookie.capture("", "https://evil.com", "", consent=True)
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
        "https://example.com/api/events", transport=transport, clock=lambda: clock[0]
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
