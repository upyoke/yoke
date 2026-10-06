import rules from './attribution_rules.json' with { type: 'json' };
/** First-party server-set, signed HttpOnly attribution cookie. Never import into a browser bundle. */
import { captureTouch, updateAttribution, domainMatches } from './events_attribution.ts';
import type { AttributionData } from './events_attribution.ts';

export const COOKIE_NAME = rules.limits.cookie_name;
export const COOKIE_SECONDS = rules.limits.cookie_seconds;
const encoder = new TextEncoder();
const b64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64 = (value: string) => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));

export async function createAttributionCookie(secret: string, siteDomain: string) {
  if (secret.length < rules.limits.signing_secret_chars || !siteDomain) throw new Error('attribution_configuration_invalid: supply a private 32-character signing secret and own site domain');
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
  const clear = `${COOKIE_NAME}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax`;
  async function read(cookie: string): Promise<AttributionData | null> {
    const value = cookie.split(';').map(v => v.trim()).find(v => v.startsWith(`${COOKIE_NAME}=`))?.slice(COOKIE_NAME.length + 1);
    if (!value) return null;
    try {
      const [payload, signature] = value.split('.');
      if (!await crypto.subtle.verify('HMAC', key, unb64(signature), encoder.encode(payload))) throw new Error();
      const decoded = JSON.parse(new TextDecoder().decode(unb64(payload)));
      if (decoded.expires <= Date.now() / 1000) return null;
      if (!decoded.record?.visitor_id || !decoded.record.first_touch || !decoded.record.last_touch) throw new Error();
      return decoded.record;
    } catch {
      console.warn('[events] attribution_cookie_reminted: invalid or rotated signature; discard old identity and capture with the current secret');
      return null;
    }
  }
  async function capture(cookie: string, url: string, referrer: string, consent: boolean) {
    if (!consent) throw new Error('consent_required: obtain consent before attribution capture');
    const host = new URL(url).hostname;
    if (!domainMatches(host, siteDomain)) throw new Error('attribution_site_mismatch: send a URL belonging to the configured site domain');
    const touch = captureTouch(url, referrer, siteDomain);
    const record = updateAttribution(await read(cookie), touch, crypto.randomUUID());
    const payload = b64(encoder.encode(JSON.stringify({ record, expires: Math.floor(Date.now() / 1000) + COOKIE_SECONDS })));
    const signature = b64(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(payload))));
    const value = `${payload}.${signature}`;
    if (value.length > rules.limits.cookie_value_chars) throw new Error('attribution_cookie_too_large: shorten campaign values or use an atomic server record keyed by visitor_id');
    return { record, setCookie: `${COOKIE_NAME}=${value}; Max-Age=${COOKIE_SECONDS}; Path=/; Secure; HttpOnly; SameSite=Lax` };
  }
  return { capture, read, clear };
}
