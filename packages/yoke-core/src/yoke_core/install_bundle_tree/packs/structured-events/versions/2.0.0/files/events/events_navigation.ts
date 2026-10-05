/** Install once; returns cleanup for client frameworks. URL changes produce one view. */
import { emitEvent } from './events.ts';
import { captureAttribution, hasConsent, onConsentChange } from './events_consent.ts';
import { sanitizeUrl } from './events_attribution.ts';

let installed = false;
export function startPageViews(): () => void {
  if (installed) throw new Error('page_views_already_started: reuse the installed tracker or call its cleanup');
  installed = true;
  let previous = window.location.href;
  let seen: string | null = null;
  let active = true;
  let revision = 0;
  const view = async (referrer: string) => {
    if (!active || !hasConsent()) return;
    const url = window.location.href;
    if (url === seen) return;
    seen = url;
    const title = document.title;
    const currentRevision = revision;
    const attribution = await captureAttribution(url, referrer);
    if (!active || !hasConsent() || currentRevision !== revision) return;
    emitEvent({ name: 'PageViewed', kind: 'analytics', eventType: 'page_view', outcome: 'completed' }, {
      page_url: sanitizeUrl(url), page_path: new URL(url).pathname,
      page_title: title, referrer: sanitizeUrl(referrer), ...attribution,
    });
  };
  const navigate = () => {
    const referrer = previous;
    previous = window.location.href;
    void view(referrer);
  };
  const originalPush = history.pushState;
  const originalReplace = history.replaceState;
  const push: History['pushState'] = function (this: History, ...args) { originalPush.apply(this, args); navigate(); };
  const replace: History['replaceState'] = function (this: History, ...args) { originalReplace.apply(this, args); navigate(); };
  history.pushState = push;
  history.replaceState = replace;
  window.addEventListener('popstate', navigate);
  const unsubscribe = onConsentChange(() => {
    revision++;
    seen = null;
    if (hasConsent()) void view(document.referrer);
  });
  void view(document.referrer);
  return () => {
    active = false; installed = false; unsubscribe();
    if (history.pushState === push) history.pushState = originalPush;
    if (history.replaceState === replace) history.replaceState = originalReplace;
    window.removeEventListener('popstate', navigate);
  };
}
