import { instantFromDate } from "./events_timestamps.mjs";
import { sanitizeUrl, isBot } from './events_attribution.ts';

let sessionId: string | null = null;
let started: string | null = null;
export function getSystemProps(): Record<string, unknown> {
  return { project: 'yoke', service: 'web' };
}
export function getSessionProps(): Record<string, unknown> {
  if (!sessionId) { sessionId = crypto.randomUUID(); started = instantFromDate(new Date(Date.now())); }
  return { session_id: sessionId, session_start_time: started };
}
export function getOrgProps(orgId?: string): Record<string, unknown> {
  // Authenticated receivers stamp actor_id and authorize org context server-side.
  return { org_id: orgId ?? null };
}
export function getPageProps(): Record<string, unknown> {
  return {
    page_url: sanitizeUrl(window.location.href), page_path: window.location.pathname,
    page_title: document.title, referrer: sanitizeUrl(document.referrer),
  };
}
export function getDeviceProps(): Record<string, unknown> {
  const ua = navigator.userAgent;
  return { user_agent: ua, is_bot: isBot(ua),
    device_type: window.innerWidth < 768 ? 'mobile' : window.innerWidth < 1024 ? 'tablet' : 'desktop' };
}
