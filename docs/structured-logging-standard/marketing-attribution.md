# Marketing attribution

The executable reference is [Structured Events Pack 4.0.0](../../packs/structured-events/versions/4.0.0/files/events/README.md).
Python and TypeScript share attribution_rules.json. Install the whole bundle;
this standard does not maintain another implementation.

Capture runs from first load with no consent state; collect only non-personal
data. The server sets a signed Secure/HttpOnly/SameSite=Lax cookie through POST
/api/events/attribution. JavaScript keeps attribution in memory.

The shape is visitor_id, first_touch and last_touch. Each touch contains
utm_source, utm_medium, utm_campaign, utm_term, utm_content, utm_id,
utm_source_platform, gclid, fbclid, msclkid, li_fat_id, referrer_domain,
acquisition_channel and captured_at. First touch never changes. Last touch
updates on external-referrer or campaign/click-id visits; direct/internal visits
preserve it. Configure the owned registrable site domain so sibling subdomains
are internal. Exact/dot-boundary suffix matching prevents netflix.com from
matching x.com. Regional search domains include google.co.uk.

Click IDs override manual/referrer classification: gclid and msclkid map to
paid_search; fbclid and li_fat_id map to paid_social, even without UTMs.
When multiple IDs occur, the shared rule order is gclid, msclkid, fbclid, li_fat_id.
This is the Pack's paid fallback policy. GA4's integrated advertising channels
also use campaign/network metadata unavailable from a click ID alone.

Attach attribution to **every frontend event** when capture succeeds.
Backend conversion code uses the same group and persists required
signup attribution on the account/actor owner. Events are disposable telemetry.

Manual-channel priority follows [GA4 definitions](https://support.google.com/analytics/answer/9756891?hl=en):
direct, cross_network, paid_shopping/search/social/video, display, paid_other,
organic_shopping/social/video/search, ai_assistant, referral, email, affiliates,
audio, sms, mobile_push_notifications, unassigned/direct. Finite case-insensitive
medium lists prevent broadcast, upload and lead_nurture from implying paid.
Unknown campaign traffic is unassigned. chatgpt.com, perplexity.ai,
gemini.google.com and copilot.microsoft.com, including utm_source=chatgpt.com,
identify ai_assistant. The Pack guide names the vocabulary and limitations.

A first-party server-set cookie avoids the script-storage cap described by
[WebKit](https://webkit.org/blog/10218/full-third-party-cookie-blocking-and-more/).
Privacy policies can still shorten retention. The cookie lasts 30 days on the
same HTTPS origin; JavaScript never writes it. For concurrent tabs or longer retention, use a signed opaque visitor id and atomic
persistence with the project's durable visitor owner. Cookie-only writes have
last-response-wins semantics across tabs and a bounded payload. The Pack guide
names signing settings, refusals and the server-record alternative.

Invalid or rotated signed cookies are discarded with attribution_cookie_reminted.
The next capture mints a fresh visitor and cookie using the current secret.
Site domains are case-insensitive, trim a trailing dot and remove leading www.

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
