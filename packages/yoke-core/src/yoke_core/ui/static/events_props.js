// Generated from the installed structured-events Pack; run build_frontend_events.
import { sanitizeUrl, isBot } from './events_attribution.js';
import { hasConsent } from './events_consent.js';

let sessionId                = null;
let started                = null;
export function getSystemProps()                          {
  return { project: 'yoke', service: 'web' };
}
export function getSessionProps()                          {
  if (!hasConsent()) return {};
  if (!sessionId) { sessionId = crypto.randomUUID(); started = new Date().toISOString(); }
  return { session_id: sessionId, session_start_time: started };
}
export function clearSession()       { sessionId = null; started = null; }
export function getOrgProps(orgId         )                          {
  // Authenticated receivers stamp actor_id and authorize org context server-side.
  return { org_id: orgId ?? null };
}
export function getPageProps()                          {
  return {
    page_url: sanitizeUrl(window.location.href), page_path: window.location.pathname,
    page_title: document.title, referrer: sanitizeUrl(document.referrer),
  };
}
export function getDeviceProps()                          {
  const ua = navigator.userAgent;
  return { user_agent: ua, is_bot: isBot(ua),
    device_type: window.innerWidth < 768 ? 'mobile' : window.innerWidth < 1024 ? 'tablet' : 'desktop' };
}
