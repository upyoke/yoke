# Marketing attribution

The executable reference is [Structured Events Pack 2.0.0](../../packs/structured-events/versions/2.0.0/files/events/README.md).
Python and TypeScript share attribution_rules.json. Install the whole bundle;
this standard does not maintain another implementation.

Consent defaults to denied. Wire setConsent to the project's consent UI. No
attribution storage or visitor id exists before consent. After consent the server
sets a signed Secure/HttpOnly/SameSite=Lax cookie through POST
/api/events/attribution; DELETE revokes it. JavaScript keeps attribution in memory.

The shape is visitor_id, first_touch and last_touch. Each touch contains
utm_source, utm_medium, utm_campaign, utm_term, utm_content, utm_id,
utm_source_platform, gclid, fbclid, msclkid, li_fat_id, referrer_domain,
acquisition_channel and captured_at. First touch never changes. Last touch
updates on external-referrer or campaign/click-id visits; direct/internal visits
preserve it. Configure the owned registrable site domain so sibling subdomains
are internal. Exact/dot-boundary suffix matching prevents netflix.com from
matching x.com. Regional search domains include google.co.uk.

Attach attribution to **every consented frontend event** when capture succeeds.
Backend conversion code uses the same consented group and persists required
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
same HTTPS origin; JavaScript never writes it. For cross-host identity,
concurrent tabs or longer retention, use a signed opaque visitor id and atomic
persistence with the project's durable visitor owner. Cookie-only writes have
last-response-wins semantics across tabs and a bounded payload. The Pack guide
names signing settings, refusals and the server-record alternative.
No compatibility reader for the old mutable cookie/session shape is provided.
