# Marketing Attribution Template

Cross-link back from [structured-logging-standard.md](../structured-logging-standard.md) for the canonical envelope, [property-groups.md](property-groups.md) for the `marketing_attribution_props` group composed below, and [js-ts-template.md](js-ts-template.md) for the frontend emitter that consumes this attribution payload.

Full attribution tracking lifecycle for frontend clients. This pattern captures how a user arrived, persists it across sessions, and attaches it to events for acquisition analysis.

## Attribution Lifecycle

1. **First-touch capture.** On first page load, extract UTM parameters from the URL and referrer from `document.referrer`. Store as a first-party cookie (`yoke_attribution`, 30-day expiry) and in `sessionStorage` for the current session.

2. **Last-touch override.** On subsequent page loads, if new UTM parameters are present in the URL, update the cookie with the new values. This allows attribution to shift if a user returns via a different campaign.

3. **Referrer domain extraction.** Parse the domain from `document.referrer` (e.g., `https://www.google.com/search?q=...` becomes `google.com`). Strip `www.` prefix.

4. **Channel inference.** Determine `acquisition_channel` from available signals using the rules below.

5. **Attachment to events.** Call `getAttributionProps()` on every frontend event. The function reads from the persisted cookie/sessionStorage and returns the `marketing_attribution_props` group.

### Cookie Schema

**Cookie name:** `yoke_attribution`
**Expiry:** 30 days (rolling -- refreshed on each visit with UTM params)
**Domain:** Current site domain (first-party)
**SameSite:** `Lax`
**Secure:** `true` in production

**Cookie value (JSON-encoded):**

```json
{
 "utm_source": "google",
 "utm_medium": "cpc",
 "utm_campaign": "spring-2026",
 "utm_term": "software delivery",
 "utm_content": "ad-variant-a",
 "referrer_domain": "google.com",
 "acquisition_channel": "paid",
 "captured_at": "2026-03-12T16:00:00.000Z"
}
```

**sessionStorage key:** `yoke_attribution_session`
Same JSON structure. Used for current-session attribution when cookie is unavailable.

### Channel Inference Rules

Channels are inferred in priority order. The first matching rule wins:

| Priority | Condition | Channel |
|---|---|---|
| 1 | `utm_medium` contains `cpc`, `ppc`, `paid`, or `ad` | `paid` |
| 2 | `utm_medium` is `email` or `utm_source` is `email` or `newsletter` | `email` |
| 3 | `utm_medium` is `social` or `utm_source` matches known social domains | `social` |
| 4 | `referrer_domain` matches a search engine (google.com, bing.com, yahoo.com, duckduckgo.com, baidu.com) | `organic` |
| 5 | `referrer_domain` is present and does not match current site domain | `referral` |
| 6 | No referrer and no UTM parameters | `direct` |

Known social domains for rule 3: `facebook.com`, `twitter.com`, `x.com`, `linkedin.com`, `instagram.com`, `reddit.com`, `youtube.com`, `tiktok.com`, `pinterest.com`, `threads.net`.

### getAttributionProps() -- Complete Implementation

```typescript
interface AttributionData {
 utm_source: string | null;
 utm_medium: string | null;
 utm_campaign: string | null;
 utm_term: string | null;
 utm_content: string | null;
 referrer_domain: string | null;
 acquisition_channel: string | null;
 captured_at: string | null;
}

const COOKIE_NAME = 'yoke_attribution';
const SESSION_KEY = 'yoke_attribution_session';
const COOKIE_DAYS = 30;

const SEARCH_ENGINES = [
 'google.com', 'bing.com', 'yahoo.com',
 'duckduckgo.com', 'baidu.com', 'yandex.com',
];

const SOCIAL_DOMAINS = [
 'facebook.com', 'twitter.com', 'x.com', 'linkedin.com',
 'instagram.com', 'reddit.com', 'youtube.com', 'tiktok.com',
 'pinterest.com', 'threads.net',
];

/**
 * Extract referrer domain from a URL string.
 * Strips www. prefix. Returns null if no referrer.
 */
function extractReferrerDomain(referrer: string): string | null {
 if (!referrer) return null;
 try {
 const url = new URL(referrer);
 return url.hostname.replace(/^www\./, '');
 } catch {
 return null;
 }
}

/**
 * Infer acquisition channel from UTM params and referrer.
 */
function inferChannel(
 utmSource: string | null,
 utmMedium: string | null,
 referrerDomain: string | null,
): string {
 // Priority 1: Paid
 if (utmMedium && /cpc|ppc|paid|ad/i.test(utmMedium)) {
 return 'paid';
 }

 // Priority 2: Email
 if (
 utmMedium === 'email' ||
 utmSource === 'email' ||
 utmSource === 'newsletter'
 ) {
 return 'email';
 }

 // Priority 3: Social
 if (utmMedium === 'social') return 'social';
 if (utmSource && SOCIAL_DOMAINS.some((d) => utmSource.includes(d))) {
 return 'social';
 }
 if (referrerDomain && SOCIAL_DOMAINS.some((d) => referrerDomain.includes(d))) {
 return 'social';
 }

 // Priority 4: Organic search
 if (referrerDomain && SEARCH_ENGINES.some((d) => referrerDomain.includes(d))) {
 return 'organic';
 }

 // Priority 5: Referral
 if (referrerDomain) {
 const currentDomain = window.location.hostname.replace(/^www\./, '');
 if (referrerDomain !== currentDomain) {
 return 'referral';
 }
 }

 // Priority 6: Direct
 return 'direct';
}

/**
 * Read UTM parameters from the current URL.
 */
function getUtmFromUrl(): Partial<AttributionData> {
 const params = new URLSearchParams(window.location.search);
 const result: Partial<AttributionData> = {};

 const utmKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'] as const;
 let hasUtm = false;

 for (const key of utmKeys) {
 const value = params.get(key);
 if (value) {
 result[key] = value;
 hasUtm = true;
 }
 }

 return hasUtm ? result : {};
}

/**
 * Set a cookie with the given name, value, and expiry in days.
 */
function setCookie(name: string, value: string, days: number): void {
 const expires = new Date(Date.now() + days * 864e5).toUTCString();
 const secure = window.location.protocol === 'https:' ? '; Secure' : '';
 document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax${secure}`;
}

/**
 * Read a cookie by name.
 */
function getCookie(name: string): string | null {
 const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
 return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Capture attribution on page load.
 * Call this once on app initialization.
 */
function captureAttribution(): void {
 const urlUtm = getUtmFromUrl();
 const referrerDomain = extractReferrerDomain(document.referrer);
 const hasNewUtm = Object.keys(urlUtm).length > 0;

 // If new UTM params present, override (last-touch)
 if (hasNewUtm) {
 const data: AttributionData = {
 utm_source: urlUtm.utm_source ?? null,
 utm_medium: urlUtm.utm_medium ?? null,
 utm_campaign: urlUtm.utm_campaign ?? null,
 utm_term: urlUtm.utm_term ?? null,
 utm_content: urlUtm.utm_content ?? null,
 referrer_domain: referrerDomain,
 acquisition_channel: inferChannel(
 urlUtm.utm_source ?? null,
 urlUtm.utm_medium ?? null,
 referrerDomain,
 ),
 captured_at: new Date().toISOString(),
 };

 setCookie(COOKIE_NAME, JSON.stringify(data), COOKIE_DAYS);
 sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
 return;
 }

 // If no existing attribution, capture referrer-only attribution
 const existing = getCookie(COOKIE_NAME);
 if (!existing) {
 const data: AttributionData = {
 utm_source: null,
 utm_medium: null,
 utm_campaign: null,
 utm_term: null,
 utm_content: null,
 referrer_domain: referrerDomain,
 acquisition_channel: inferChannel(null, null, referrerDomain),
 captured_at: new Date().toISOString(),
 };

 setCookie(COOKIE_NAME, JSON.stringify(data), COOKIE_DAYS);
 sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
 }
}

/**
 * Get stored attribution data for attaching to events.
 * Reads from sessionStorage first, falls back to cookie.
 */
function getStoredAttribution(): AttributionData {
 const empty: AttributionData = {
 utm_source: null,
 utm_medium: null,
 utm_campaign: null,
 utm_term: null,
 utm_content: null,
 referrer_domain: null,
 acquisition_channel: null,
 captured_at: null,
 };

 // Try sessionStorage first (faster)
 const session = sessionStorage.getItem(SESSION_KEY);
 if (session) {
 try {
 return { ...empty, ...JSON.parse(session) };
 } catch {
 // Fall through to cookie
 }
 }

 // Fall back to cookie
 const cookie = getCookie(COOKIE_NAME);
 if (cookie) {
 try {
 return { ...empty, ...JSON.parse(cookie) };
 } catch {
 return empty;
 }
 }

 return empty;
}

/**
 * Get attribution properties for the marketing_attribution_props group.
 * This is the function called by the event emitter.
 */
function getAttributionProps(): Record<string, string | null> {
 const data = getStoredAttribution();
 return {
 utm_source: data.utm_source,
 utm_medium: data.utm_medium,
 utm_campaign: data.utm_campaign,
 utm_term: data.utm_term,
 utm_content: data.utm_content,
 referrer_domain: data.referrer_domain,
 acquisition_channel: data.acquisition_channel,
 };
}

export {
 captureAttribution,
 getAttributionProps,
 getStoredAttribution,
 extractReferrerDomain,
 inferChannel,
 type AttributionData,
};
```

---

