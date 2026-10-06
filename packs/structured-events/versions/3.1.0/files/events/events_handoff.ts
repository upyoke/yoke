/** Server-only signed attribution transfer; durable atomic consumption is project-owned. */
import { createAttributionCookie, validateRecord } from './events_cookie.ts';

export const HANDOFF_SECONDS = 120;
const purpose = 'attribution_handoff';
const encoder = new TextEncoder();
const b64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64 = (value: string) => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
export function handoffOrigin(value: string): string {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash || value.endsWith('/')) throw new Error();
    return url.origin;
  } catch { throw new Error('attribution_handoff_origin_invalid: supply an exact HTTPS destination origin without a path'); }
}
export async function createAttributionHandoff(secret: string, siteDomain: string) {
  const cookie = await createAttributionCookie(secret, siteDomain);
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
  async function mint(header: string, audience: string) {
    const record = await cookie.readVerified(header);
    audience = handoffOrigin(audience);
    const expires = Math.floor(Date.now() / 1000) + HANDOFF_SECONDS;
    const payload = b64(encoder.encode(JSON.stringify({ purpose, audience, expires, nonce: crypto.randomUUID(), record })));
    const signature = b64(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(purpose + ':' + payload))));
    return { token: `${payload}.${signature}`, expires_at: expires };
  }
  async function redeem(token: string, audience: string, consume: (nonce: string, expires: number) => Promise<boolean>) {
    audience = handoffOrigin(audience);
    let decoded;
    try {
      if (typeof token !== 'string' || token.length > 8192) throw new Error();
      const parts = token.split('.');
      if (parts.length !== 2) throw new Error();
      const [payload, signature] = parts;
      if (!await crypto.subtle.verify('HMAC', key, unb64(signature), encoder.encode(purpose + ':' + payload))) throw new Error();
      decoded = JSON.parse(new TextDecoder().decode(unb64(payload)));
      if (decoded.purpose !== purpose || !Number.isInteger(decoded.expires) ||
        typeof decoded.nonce !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(decoded.nonce)) throw new Error();
      validateRecord(decoded.record);
    } catch { throw new Error('attribution_handoff_invalid: restart sign-in from the consented source origin'); }
    if (decoded.expires <= Date.now() / 1000) throw new Error('attribution_handoff_expired: restart sign-in to mint a fresh token');
    if (decoded.audience !== audience) throw new Error('attribution_handoff_audience_mismatch: redeem at the exact destination origin used when minting');
    const setCookie = await cookie.write(decoded.record);
    if (!await consume(decoded.nonce, decoded.expires)) throw new Error('attribution_handoff_replayed: restart sign-in to mint a fresh one-time token');
    return { record: decoded.record, setCookie };
  }
  return { mint, redeem };
}
