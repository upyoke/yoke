/**
 * One tracker per document; returns cleanup for client frameworks. A path
 * change produces one view; query-only and hash-only changes (filters, the
 * app's own replaceState rewrites) produce none. The owner marker lives on
 * window, so separately bundled copies of this module (a host page and an
 * embedded app) share it.
 */
import { emitEvent } from './events.ts';
import { captureAttribution } from './events_capture.ts';
import { sanitizePath, sanitizeUrl } from './events_attribution.ts';

const TRACKER = Symbol.for('structured-events.page-views');
export function startPageViews(): () => void {
  const marker = window as unknown as Record<symbol, object | undefined>;
  if (marker[TRACKER]) {
    console.warn('[events] page_views_already_started: this document already tracks page views; reuse that tracker or call its cleanup before starting another');
    return () => {};
  }
  const owner = {};
  marker[TRACKER] = owner;
  let previous = window.location.href;
  let seen: string | null = null;
  let active = true;
  const view = async (referrer: string) => {
    if (!active) return;
    const url = window.location.href;
    const path = window.location.pathname;
    if (path === seen) return;
    seen = path;
    const title = document.title;
    const attribution = await captureAttribution(url, referrer);
    if (!active) return;
    emitEvent({ name: 'PageViewed', kind: 'analytics', eventType: 'page_view', outcome: 'completed' }, {
      page_url: sanitizeUrl(url), page_path: sanitizePath(path),
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
  void view(document.referrer);
  return () => {
    active = false;
    if (marker[TRACKER] === owner) delete marker[TRACKER];
    if (history.pushState === push) history.pushState = originalPush;
    if (history.replaceState === replace) history.replaceState = originalReplace;
    window.removeEventListener('popstate', navigate);
  };
}
