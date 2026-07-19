/**
 * Shared event-attribution helpers. See events/README.md.
 */

import type { AttributionData } from './events_types';

// ---------------------------------------------------------------------------
// Marketing Attribution (Section E)
// ---------------------------------------------------------------------------

const COOKIE_NAME = '{{project_name}}_attribution';
const SESSION_KEY = '{{project_name}}_attribution_session';
const COOKIE_DAYS = 30;

const SEARCH_ENGINES = [
  'google.com',
  'bing.com',
  'yahoo.com',
  'duckduckgo.com',
  'baidu.com',
  'yandex.com',
];

const SOCIAL_DOMAINS = [
  'facebook.com',
  'twitter.com',
  'x.com',
  'linkedin.com',
  'instagram.com',
  'reddit.com',
  'youtube.com',
  'tiktok.com',
  'pinterest.com',
  'threads.net',
];

/**
 * Extract referrer domain from a URL string.
 * Strips www. prefix. Returns null if no referrer.
 */
export function extractReferrerDomain(referrer: string): string | null {
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
 *
 * Rules are applied in priority order -- first match wins:
 * 1. utm_medium contains cpc/ppc/paid/ad -> paid
 * 2. utm_medium is email OR utm_source is email/newsletter -> email
 * 3. utm_medium is social OR utm_source/referrer matches social domains -> social
 * 4. referrer_domain matches search engines -> organic
 * 5. referrer_domain present and not current site -> referral
 * 6. No referrer and no UTM -> direct
 */
export function inferChannel(
  utmSource: string | null,
  utmMedium: string | null,
  referrerDomain: string | null
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
  if (
    referrerDomain &&
    SOCIAL_DOMAINS.some((d) => referrerDomain.includes(d))
  ) {
    return 'social';
  }

  // Priority 4: Organic search
  if (
    referrerDomain &&
    SEARCH_ENGINES.some((d) => referrerDomain.includes(d))
  ) {
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

  const utmKeys = [
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_term',
    'utm_content',
  ] as const;
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
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name}=([^;]*)`)
  );
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Capture attribution on page load.
 *
 * Call this once on app initialization (e.g., in _app.tsx or layout.tsx).
 * Implements the full attribution lifecycle from Section E:
 * - First-touch capture from UTM params and referrer
 * - Last-touch override when new UTM params are present
 * - Persists to first-party cookie (30-day, rolling) and sessionStorage
 */
export function captureAttribution(): void {
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
        referrerDomain
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
export function getStoredAttribution(): AttributionData {
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
 * This is the function called by the event emitter on every event.
 */
export function getAttributionProps(): Record<string, string | null> {
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
