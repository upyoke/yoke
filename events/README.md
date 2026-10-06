# Structured Events integration

Install all sibling modules and attribution_rules.json. Runtime configuration
belongs to the consuming project. TypeScript uses explicit .ts imports and JSON
import attributes; configure your bundler accordingly. Tests require Node >=22.6
and pytest. The new storage shape has no compatibility reader for old cookies.

## Consent and browser setup

```typescript
import { configureEvents, setConsent } from './events.ts';
import { startPageViews } from './events_navigation.ts';
configureEvents({ publishableKey: 'project-public-key' });
const stop = startPageViews();
await setConsent(consentManager.analyticsAllowed());
// Wire revocation to await setConsent(false), and unmount to stop().
```

Consent defaults to denied. No attribution request, cookie, browser storage or
visitor id is created before consent. Session identity is in memory. Emitting
before consent returns null. Grant captures the current landing URL/referrer
before notifying page tracking. Revocation clears memory, session and queue,
then DELETEs the server cookie. A failure warns consent_clear_failed and teaches
retry. Keep the landing URL until the consent callback if you need attribution;
do not store denied visits for later replay.

Page tracking emits an initial view and URL-changing pushState, replaceState and
popstate views. State-only updates are deduped. Each view keeps its URL, title and
previous-page referrer across asynchronous capture. Install once; do not also
emit the initial PageViewed manually. Cleanup restores the history methods.

## Attribution and persistence

Every consented frontend event carries visitor_id, first_touch and last_touch
when server capture succeeds. Each touch has the classic five UTMs, utm_id,
utm_source_platform, gclid, fbclid, msclkid, li_fat_id, referrer_domain,
acquisition_channel and captured_at. First touch never changes; last touch
updates on external-referrer or campaign/click-id visits. Direct/internal returns
preserve it. Configure siteDomain as your owned registrable domain so sibling
subdomains are internal. Domain matching is exact or a dot-boundary suffix.

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

For cross-host identity, concurrent tabs, longer retention or large campaigns,
replace the payload with a signed opaque visitor id and atomic persistence with
the project's existing durable visitor owner. Cookie-only writes have
last-response-wins semantics across tabs and a 3800-character value limit; size
refusals teach the server-record path. First touch persists across ordinary
sessions on the same origin. Required signup attribution belongs to the durable
account/actor owner, never reconstructed from disposable events.

## Anonymous collector and attribution routes

api-route.ts exports framework-neutral createCollector and
createAttributionHandler. Wire POST /api/events and POST/DELETE
/api/events/attribution. Supply these project-owned dependencies:

- publishableKey (public routing key), allowedOrigins (exact scheme/host/port).
- Shared rateLimit keyed by trusted client and collector/project identity before
  decoding. Do not trust a browser-provided IP header.
- writeEvents that accepts/deduplicates event_id before reporting success. Stamp
  authoritative actor/org/project identity from server context; the collector
  deletes client actor/org ids. Client attribution is untrusted telemetry.
- signingSecret and siteDomain for attribution. Capture requires consent:true
  and a site URL. DELETE clears the cookie. Cookies require HTTPS.

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
telemetry delivery. Revocation discards queued telemetry. Python EventBatch uses
the same bounded requeue/backoff rule; the process schedules flush after retry_at.
Use EventBatch(endpoint, publishable_key, transport=transport), or pass
publishable_key to emit_event/emit_event_obj for HTTP destinations. The key is
sent as X-Events-Key; a missing key reports publishable_key_required.
Invalid/rotated signatures report attribution_cookie_reminted; consented capture
mints a fresh visitor and signed cookie. Domain matching normalizes case, trailing
dots and leading www in both languages.

Both languages strip sensitive query keys (token, auth code, password, email,
signing credentials), userinfo and fragments from page_url and referrer. This
denylist is not a PII detector: keep secrets out of paths, campaigns and context.
Both flag bot/headless/preview user agents; the collector stamps the flag from
the real request User-Agent.

Run python3 -m pytest events and
node --experimental-strip-types --test events/test_browser.mjs. Tests execute
classification in both languages, signed cookies, consent, identity, SPA views,
network/429/5xx retries, permanent refusal drops, bounded queues, key routing,
cookie rotation/domain parity, URL hygiene, bot flags and anonymous collector checks.
