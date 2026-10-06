"""Attribution and URL hygiene; same rules as the browser."""

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RULES = json.loads(Path(__file__).with_name("attribution_rules.json").read_text())


def domain_matches(host: str, domain: str) -> bool:
    host = host.lower().removeprefix("www.").rstrip(".")
    domain = domain.lower().removeprefix("www.").rstrip(".")
    return host == domain or host.endswith("." + domain)


def extract_referrer_domain(value: str) -> str | None:
    try:
        return (urlsplit(value).hostname or "").lower().removeprefix("www.") or None
    except ValueError:
        return None


def infer_channel(source=None, medium=None, referrer=None, campaign="") -> str:
    s, m = (source or referrer or "").lower(), (medium or "").lower()

    def matches(key):
        return any(domain_matches(s, d) for d in RULES[key])

    ai = matches("ai_domains")
    # Provider subdomains such as Gemini are AI sources, not Google Search.
    search = not ai and (matches("search_domains") or s in ("google", "bing", "yahoo"))
    social, video = matches("social_domains"), matches("video_domains")
    shopping = matches("shopping_domains") or re.search(
        r"(^|[^a-z])(shop|shopping)", campaign, re.I
    )
    if s == "(direct)" and m in ("(none)", "(not set)"):
        return "direct"
    if "cross-network" in campaign.lower():
        return "cross_network"
    if m in RULES["paid_mediums"]:
        for match, channel in (
            (shopping, "paid_shopping"),
            (search, "paid_search"),
            (social, "paid_social"),
            (video, "paid_video"),
        ):
            if match:
                return channel
    if m in RULES["display_mediums"]:
        return "display"
    if m in RULES["paid_mediums"]:
        return "paid_other"
    if shopping:
        return "organic_shopping"
    if social or m in RULES["social_mediums"]:
        return "organic_social"
    if video or m in RULES["video_mediums"]:
        return "organic_video"
    if search or m == "organic":
        return "organic_search"
    if ai or m == "ai-assistant":
        return "ai_assistant"
    if m in ("referral", "app", "link"):
        return "referral"
    if s in RULES["email_mediums"] or s == "newsletter" or m in RULES["email_mediums"]:
        return "email"
    if m == "affiliate":
        return "affiliates"
    if m == "audio":
        return "audio"
    if s == "sms" or m == "sms":
        return "sms"
    if s == "firebase" or m in RULES["push_mediums"]:
        return "mobile_push_notifications"
    if referrer:
        return "referral"
    return "unassigned" if s or m or campaign else "direct"


def capture_touch(url, referrer, site_domain, now):
    params = {}
    for key, value in parse_qsl(urlsplit(url).query):
        params.setdefault(key, value)
    touch = {key: params.get(key) or None for key in RULES["campaign_keys"]}
    domain = extract_referrer_domain(referrer)
    if domain and domain_matches(domain, site_domain):
        domain = None
    touch.update(referrer_domain=domain, captured_at=now)
    touch["acquisition_channel"] = infer_channel(
        touch["utm_source"], touch["utm_medium"], domain, touch["utm_campaign"] or ""
    )
    for key, channel in RULES["paid_click_ids"].items():
        if touch[key]:
            touch["acquisition_channel"] = channel
            break
    return touch


def update_attribution(existing, touch, visitor_id):
    acquisition = touch["referrer_domain"] or any(
        touch[k] for k in RULES["campaign_keys"]
    )
    return {
        "visitor_id": existing["visitor_id"] if existing else visitor_id,
        "first_touch": existing["first_touch"] if existing else touch,
        "last_touch": touch if not existing or acquisition else existing["last_touch"],
    }


def get_attribution_props(record):
    return dict(record) if record else {}


def sanitize_url(value):
    try:
        url = urlsplit(value)
        if url.scheme not in ("https", "http") or not url.hostname:
            return None
        host = url.hostname
        if ":" in host:
            host = f"[{host}]"
        if url.port:
            host += f":{url.port}"
        params = [
            (k, v)
            for k, v in parse_qsl(url.query, keep_blank_values=True)
            if k.lower() not in RULES["sensitive_query_keys"]
        ]
        return urlunsplit((url.scheme, host, url.path or "/", urlencode(params), ""))
    except ValueError:
        return None


def is_bot(user_agent):
    return bool(re.search(RULES["bot_pattern"], user_agent, re.I))
