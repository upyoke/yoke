/** Pure attribution rules; shared data is also consumed by Python. */
import rules from './attribution_rules.json' with { type: 'json' };

export type Touch = Record<string, string | null>;
export interface AttributionData {
  visitor_id: string;
  first_touch: Touch;
  last_touch: Touch;
}

export function domainMatches(host: string, domain: string): boolean {
  host = host.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
  domain = domain.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
  return host === domain || host.endsWith(`.${domain}`);
}

export function extractReferrerDomain(referrer: string): string | null {
  try { return new URL(referrer).hostname.toLowerCase().replace(/^www\./, ''); }
  catch { return null; }
}

export function inferChannel(source: string | null, medium: string | null,
  referrer: string | null, campaign = ''): string {
  const s = (source || referrer || '').toLowerCase();
  const m = (medium || '').toLowerCase();
  const matches = (domains: string[]) => domains.some(d => domainMatches(s, d));
  const ai = matches(rules.ai_domains);
  // Provider subdomains such as Gemini are AI sources, not Google Search.
  const search = !ai && (matches(rules.search_domains) || ['google', 'bing', 'yahoo'].includes(s));
  const social = matches(rules.social_domains);
  const video = matches(rules.video_domains);
  const shopping = matches(rules.shopping_domains) || /(^|[^a-z])(shop|shopping)/i.test(campaign);
  // GA4 manual-channel priority, with a finite medium vocabulary.
  if (s === '(direct)' && ['(none)', '(not set)'].includes(m)) return 'direct';
  if (campaign.toLowerCase().includes('cross-network')) return 'cross_network';
  if (rules.paid_mediums.includes(m)) {
    if (shopping) return 'paid_shopping';
    if (search) return 'paid_search';
    if (social) return 'paid_social';
    if (video) return 'paid_video';
  }
  if (rules.display_mediums.includes(m)) return 'display';
  if (rules.paid_mediums.includes(m)) return 'paid_other';
  if (shopping) return 'organic_shopping';
  if (social || rules.social_mediums.includes(m)) return 'organic_social';
  if (video || rules.video_mediums.includes(m)) return 'organic_video';
  if (search || m === 'organic') return 'organic_search';
  if (ai || m === 'ai-assistant') return 'ai_assistant';
  if (['referral', 'app', 'link'].includes(m)) return 'referral';
  if (rules.email_mediums.includes(s) || s === 'newsletter' || rules.email_mediums.includes(m)) return 'email';
  if (m === 'affiliate') return 'affiliates';
  if (m === 'audio') return 'audio';
  if (s === 'sms' || m === 'sms') return 'sms';
  if (s === 'firebase' || rules.push_mediums.includes(m)) return 'mobile_push_notifications';
  if (referrer) return 'referral';
  return s || m || campaign ? 'unassigned' : 'direct';
}

export function captureTouch(url: string, referrer: string, siteDomain: string,
  now = new Date().toISOString()): Touch {
  const params = new URL(url).searchParams;
  const touch: Touch = Object.fromEntries(rules.campaign_keys.map(k => [k, params.get(k) || null]));
  let domain = extractReferrerDomain(referrer);
  if (domain && domainMatches(domain, siteDomain)) domain = null;
  touch.referrer_domain = domain;
  touch.acquisition_channel = inferChannel(touch.utm_source, touch.utm_medium, domain, touch.utm_campaign || '');
  touch.captured_at = now;
  return touch;
}

export function updateAttribution(existing: AttributionData | null, touch: Touch,
  visitorId: string): AttributionData {
  const acquisition = !!touch.referrer_domain || rules.campaign_keys.some(k => !!touch[k]);
  return {
    visitor_id: existing?.visitor_id || visitorId,
    first_touch: existing?.first_touch || touch,
    last_touch: !existing || acquisition ? touch : existing.last_touch,
  };
}

export function sanitizeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol)) return null;
    url.username = ''; url.password = ''; url.hash = '';
    for (const key of [...url.searchParams.keys()]) {
      if (rules.sensitive_query_keys.includes(key.toLowerCase())) url.searchParams.delete(key);
    }
    return url.href;
  } catch { return null; }
}

export function isBot(userAgent: string): boolean {
  return new RegExp(rules.bot_pattern, 'i').test(userAgent);
}
