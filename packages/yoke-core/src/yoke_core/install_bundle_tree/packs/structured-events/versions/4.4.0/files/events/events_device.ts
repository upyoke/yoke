/**
 * Server-side browser, OS and device classification for collected events.
 * The collector is the only authority: it parses the request User-Agent with
 * Bowser and lets the default User-Agent Client Hints override it. Viewport
 * size is a layout signal and never decides device type.
 */
import Bowser from 'bowser';

const MOBILE_OS = new Set(['Android', 'iOS', 'Windows Phone', 'KaiOS']);

function hint(headers: Headers, name: string): string | null {
  const value = headers.get(name);
  return value ? value.trim().replace(/^"|"$/g, '') : null;
}

function deviceType(platformType: string | undefined, os: string | null, mobile: string | null): string {
  if (mobile === '?1') return 'mobile';
  if (platformType === 'tablet') return 'tablet';
  if (mobile === null && (platformType === 'mobile' || MOBILE_OS.has(os || ''))) return 'mobile';
  return 'desktop';
}

export function deviceProps(headers: Headers): Record<string, string | null> {
  const userAgent = headers.get('User-Agent') || '';
  const mobile = hint(headers, 'Sec-CH-UA-Mobile');
  const parsed = userAgent ? Bowser.parse(userAgent) : null;
  const os = hint(headers, 'Sec-CH-UA-Platform') || parsed?.os.name || null;
  return {
    browser: parsed?.browser.name || null,
    browser_version: parsed?.browser.version || null,
    os,
    device_type: parsed || mobile !== null ? deviceType(parsed?.platform.type, os, mobile) : null,
  };
}
