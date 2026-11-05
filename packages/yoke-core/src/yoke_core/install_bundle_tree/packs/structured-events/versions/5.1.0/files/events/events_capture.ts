/** Browser attribution capture. Attribution stays in memory, persistence is server-owned. */
import type { AttributionData } from './events_attribution.ts';

let stored: AttributionData | null = null;
let endpoint = '/api/events/attribution';
let publishableKey = '';
let pending: Promise<AttributionData | null> = Promise.resolve(null);

export function configureAttribution(url: string, key: string): void {
  endpoint = url; publishableKey = key;
}
export function getStoredAttribution(): AttributionData | null { return stored; }
export function getAttributionProps(): Record<string, unknown> {
  return stored ? { ...stored } : {};
}

/** Captures serially, so each landing updates the server record in order. */
export async function captureAttribution(url = window.location.href,
  referrer = document.referrer): Promise<AttributionData | null> {
  const run = pending.then(async () => {
    try {
      const response = await fetch(endpoint, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Events-Key': publishableKey },
        body: JSON.stringify({ url, referrer }),
      });
      if (!response.ok) throw new Error(`attribution_capture_refused: HTTP ${response.status}`);
      const data = await response.json();
      if (!data?.visitor_id || !data?.first_touch || !data?.last_touch) {
        throw new Error('attribution_response_invalid');
      }
      stored = data;
      return stored;
    } catch (error) {
      console.warn('[events] attribution_capture_failed: check collector configuration and reload to capture again', error);
    }
    return null;
  });
  pending = run;
  return run;
}
