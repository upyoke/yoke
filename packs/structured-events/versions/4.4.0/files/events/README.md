# Structured Events integration

Install all sibling modules and attribution_rules.json. Runtime configuration
belongs to the consuming project. TypeScript uses explicit .ts imports and JSON
import attributes; configure your bundler accordingly. Tests require Node >=22.6
and pytest. The collector's device classification needs one parser per
language: add ua-parser[regex]>=1.0 to Python dependencies (events_device.py
refuses to import with events_device_parser_missing until it is installed) and
bowser to package.json for api-route.ts.

## Browser setup

```typescript
import { configureEvents } from './events.ts';
import { startPageViews } from './events_navigation.ts';
configureEvents({ publishableKey: 'project-public-key' });
const stop = startPageViews();
// Wire unmount to stop().
```

Collection starts on first load; there is no consent state. Each page view
captures attribution for its URL and referrer before it emits, so the first view
carries the landing touch. The server owns the visitor cookie; the browser keeps
no attribution storage, and session identity stays in memory. Collect only
non-personal data through this Pack.

Page tracking emits an initial view and one view per path change through
pushState, replaceState or popstate. A navigation that changes only the query or
fragment (a filter click, the app's own replaceState rewrite such as
?selection=all) or only history state emits nothing. Each view keeps its URL,
title and previous-page referrer across asynchronous capture. One tracker runs per
document, even across separately bundled copies of this module (a host page and
an embedded app): a second startPageViews warns page_views_already_started and
returns a no-op cleanup, so only the first tracker records views. Do not also
emit the initial PageViewed manually. Cleanup restores the history methods and
releases the document for a new tracker.

## Attribution and persistence

Every frontend event carries visitor_id, first_touch and last_touch
when server capture succeeds. Each touch has the classic five UTMs, utm_id,
utm_source_platform, gclid, fbclid, msclkid, li_fat_id, referrer_domain,
acquisition_channel and captured_at. First touch never changes; last touch
updates on external-referrer or campaign/click-id visits. Direct/internal returns
preserve it. Configure siteDomain as your owned registrable domain (example.com,
not app.example.com) so the apex and sibling subdomains are internal. Domain
matching is exact or a dot-boundary suffix.

Sign-in hops are internal too. After an identity-provider round trip the first
page's referrer is the provider host, not an acquisition source.
excluded_referrer_domains in attribution_rules.json lists those hosts
(accounts.google.com, accounts.youtube.com, Microsoft, Apple, Okta, Auth0,
OneLogin and Cognito sign-in). A referrer matching siteDomain or that list
records referrer_domain null: it never replaces last touch and a first visit
from it is direct. Add your own identity provider's host there; never list a
host that also sends real visitors (github.com, a bare google.com).

Click IDs override manual/referrer classification: gclid and msclkid map to
paid_search; fbclid and li_fat_id map to paid_social, even without UTMs.
When multiple IDs occur, the shared rule order is gclid, msclkid, fbclid, li_fat_id.
This is the Pack's paid fallback policy. GA4's integrated advertising channels
also use campaign/network metadata unavailable from a click ID alone.

Manual-channel priority follows GA4: direct, cross-network, paid shopping/search/
social/video, display, paid other, organic shopping/social/video/search, AI
assistant, referral, email, affiliates, audio, SMS, mobile push, unassigned/direct.
Mediums use finite case-insensitive lists. The source lists are a finite vocabulary,
not Google's complete evolving catalogue; add verified regional domains there.
broadcast, lead_nurture and upload never imply paid; netflix.com never matches
x.com. AI domains and utm_source=chatgpt.com identify ai_assistant.

The server sets a signed __Host-events_attribution cookie containing visitor_id
and both touches: 30 days, Path=/, Secure, HttpOnly, SameSite=Lax, no Domain.
Python AttributionCookie and TypeScript createAttributionCookie share its wire
format. Use a private >=32-character signing secret, HTTPS and a same-origin
attribution endpoint with Cache-Control: no-store. JavaScript never sets it.
The first-party HTTP Set-Cookie path avoids Safari's script-storage cap. Browser
privacy policies can still shorten storage; no cookie guarantees retention.

For concurrent tabs, longer retention or large campaigns,
replace the payload with a signed opaque visitor id and atomic persistence with
the project's existing durable visitor owner. Cookie-only writes have
last-response-wins semantics across tabs and a 3800-character value limit; size
refusals teach the server-record path. First touch persists across ordinary
sessions on the same origin. Required signup attribution belongs to the durable
account/actor owner, never reconstructed from disposable events.

## Anonymous collector and attribution routes

api-route.ts exports framework-neutral createCollector and
createAttributionHandler. Wire POST /api/events and GET/POST
/api/events/attribution. Supply these project-owned dependencies:

- publishableKey (public routing key), allowedOrigins (exact scheme/host/port).
- Shared rateLimit keyed by trusted client and collector/project identity before
  decoding. Do not trust a browser-provided IP header.
- writeEvents that accepts/deduplicates event_id before reporting success. Stamp
  authoritative actor/org/project identity from server context; the collector
  deletes client actor/org ids. Client attribution is untrusted telemetry.
- signingSecret and siteDomain for attribution. Capture requires a site URL
  and referrer. Cookies require HTTPS.
- Optional recordRefusal, a disposable diagnostic sink. Every handler passes it
  {refusal_id, reason, status, route, origin, host, window_start} at most once
  per refusal kind (reason, status, route) per minute in each process; store it
  deduplicated by refusal_id so all processes keep one row per kind per minute.
  It never receives a request body, cookie, key or client address, the Origin
  is truncated to 200 characters, and a failing sink logs
  collector_refusal_record_failed while the caller still gets its refusal.

Anonymous frontend analytics need no bearer token. Origin/key checks prevent
accidental and drive-by writes, not forged non-browser requests. Backend/audit/
security events use separate authenticated authorization. Same-origin is the
reference path; cross-origin CORS/preflight belongs to the consuming project.

Requests contain {events:[...]} with 1..50 envelopes, <=512 KB request, <=64 KB
envelope, session_id and ISO event_time. Refusals include publishable_key_invalid
(401), origin_not_allowed (403), rate_limited (429 with Retry-After),
envelope_invalid (400), payload_too_large/event_too_large (413),
collector_unavailable (503). Each names recovery. Failed sinks return failure,
never accepted. Retry with the same event ids for dedupe.

The collector stamps every accepted envelope with received_at (its own receipt
time), client_time_offset_seconds (event_time minus receipt; negative when the
event was queued or the client clock runs behind) and client_time_skewed (true
beyond CLIENT_TIME_TOLERANCE_SECONDS, 300). Store received_at as the row time
so ordering and time-based reports never depend on a browser clock; event_time
stays in the envelope as the client's claim. Skewed events are still accepted.

## Browser, OS and device type

The collector is the only authority for is_bot, browser, browser_version, os
and device_type: it derives them from each request's headers and overwrites
whatever an emitter sent. events_device.py (device_props, ua-parser) and
events_device.ts (deviceProps, Bowser) parse the User-Agent, then apply the
User-Agent Client Hints browsers send by default: Sec-CH-UA-Platform names os,
and Sec-CH-UA-Mobile ?1 means mobile. Otherwise the parser's tablet or mobile
classification (iPad, Android without a mobile token, a phone OS) wins, and
everything else is desktop. A request without a User-Agent records nulls.
Browser names are each parser's own (Python: Mobile Safari, Chrome Mobile;
TypeScript: Safari, Chrome). The browser sends only user_agent and is_bot;
viewport width is layout, never device type. A relay in front of the collector
forwards User-Agent, Sec-CH-UA-Mobile and Sec-CH-UA-Platform unchanged.

## Delivery and privacy

One fetch per batch; no parallel beacon. Only network failures, 429 and 5xx
requeue in order. 429 honors Retry-After seconds or date. Other HTTP refusals
discard the batch and report batch_refused with the collector's error and
recovery (or collector_http_STATUS). Fix configuration/payload before new sends.
Queues hold at most 500 pending events: append drops the oldest; requeue keeps
retry ids and discards the newest overflow, reporting batch_queue_full.
Concurrent flushes share an in-flight
promise; visibility hidden uses that same path. Ordinary batches stay below
keepalive's payload budget; large single envelopes use ordinary fetch.
Memory queues can be lost when tabs terminate. Product work must not depend on
telemetry delivery. Python EventBatch uses
the same bounded requeue/backoff rule; the process schedules flush after retry_at.
Use EventBatch(endpoint, publishable_key, transport=transport), or pass
publishable_key to emit_event/emit_event_obj for HTTP destinations. The key is
sent as X-Events-Key; a missing key reports publishable_key_required.
Invalid/rotated signatures report attribution_cookie_reminted; capture
mints a fresh visitor and signed cookie. Domain matching normalizes case, trailing
dots and leading www in both languages.

Both languages strip sensitive query keys (token, auth code, device-login
user_code, password, email, signing credentials), userinfo and fragments from
page_url and referrer, and replace the path segment after a
sensitive_path_parents entry (machine-approval, so /machine-approval/<code>
becomes /machine-approval/redacted) in page_url, page_path and referrer. The
browser and the collector apply the same attribution_rules.json lists. This
denylist is not a PII detector: keep other secrets out of paths, campaigns and
context.
Both flag bot/headless/preview user agents; the collector stamps the flag from
the real request User-Agent.

Run python3 -m pytest events and
node --experimental-strip-types --test events/test_browser.mjs. Tests execute
classification in both languages, signed cookies, identity, SPA views,
network/429/5xx retries, permanent refusal drops, bounded queues, key routing,
cookie rotation/domain parity, URL hygiene, bot flags, device classification
and anonymous collector checks.

## Verified attribution and sign-in hand-off

GET /api/events/attribution verifies the signed cookie and returns the record:
visitor_id, first_touch and last_touch.
It never sets, clears or re-mints a cookie. Missing cookies refuse with
attribution_absent; expired, malformed or tampered cookies refuse with
attribution_invalid. Responses use Cache-Control: no-store. A verified record
keeps visitor_id, first_touch and last_touch and ignores any other key; a record
missing one of them is invalid, so capture again.

To carry attribution between isolated __Host- cookies, POST
/api/events/attribution/handoff at the source origin with
{"audience":"https://app.example.com"}. It verifies the cookie and returns
{token, expires_at}; expires_at is Unix seconds. No cookie is changed. Carry the
token through the sign-in hand-off, then POST {"token":"..."} to
/api/events/attribution/handoff/redeem at that exact destination. Redemption
returns the verified record and sets the destination's Secure/HttpOnly cookie,
preserving visitor identity and both touches. Persist required
signup attribution on the durable account owner from this server result only.

Tokens are signed, destination-bound and valid for 120 seconds. They are bearer
secrets: carry via a server sign-in session or POST body, exclude them from
URLs, referrers, logs and telemetry, and discard them after redemption. Both
origins must use the same engine-owned collector signing identity and durable
nonce ledger; unrelated universes cannot redeem one another's tokens. Each
request supplies that serving origin's Origin and X-Events-Key headers. CORS is
unnecessary when each origin calls its own serving endpoint. The server-side
signup caller forwards the cookie plus those headers, or redeems the token;
it never receives the signing key and never trusts browser attribution fields.

Python exports AttributionCookie.read_verified and AttributionHandoff.mint /
redeem. TypeScript exports readVerified and createAttributionHandoff; wire
createAttributionHandoffHandler alongside createAttributionHandler. The consuming
project supplies consumeNonce(nonce, expires), an atomic durable insert returning
true exactly once and false for replay; failures must raise. The engine uses
frontend_attribution_redemptions keyed by org and nonce. It stores no attribution
payload in that ledger and deletes expired tombstones on redemption. Rate
counters and nonce tombstones are operational state, never disposable events.

Refusals name attribution_handoff_invalid (forgery/malformed token),
attribution_handoff_expired, attribution_handoff_replayed,
attribution_handoff_audience_mismatch, attribution_handoff_origin_invalid,
or attribution_handoff_unavailable (storage failure). Restart sign-in from the
source origin for a fresh token; use the exact HTTPS audience without a path.
Storage failures require restoring the durable nonce store before restarting.
Hand-off tokens are minted only from a verified cookie. The local HTTP collector supports cookie read/capture, while cross-origin
hand-off requires HTTPS at both ends. A minted bearer token remains redeemable
until expiry or consumption.
