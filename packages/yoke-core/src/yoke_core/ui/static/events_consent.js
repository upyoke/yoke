// Generated from the installed structured-events Pack; run build_frontend_events.
/** Browser consent lifecycle. Attribution stays in memory, persistence is server-owned. */
                                                               

let consent = false;
let stored                         = null;
let generation = 0;
let endpoint = '/api/events/attribution';
let publishableKey = '';
let pending                                  = Promise.resolve(null);
const listeners = new Set            ();

export function configureAttribution(url        , key        )       {
  endpoint = url; publishableKey = key;
}
export function hasConsent()          { return consent; }
export function getStoredAttribution()                         { return consent ? stored : null; }
export function getAttributionProps()                          {
  return consent && stored ? { ...stored } : {};
}
export function onConsentChange(listener            )             {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export async function captureAttribution(url = window.location.href,
  referrer = document.referrer)                                  {
  if (!consent) return null;
  const revision = generation;
  const run = pending.then(async () => {
    if (!consent || revision !== generation) return null;
    try {
      const response = await fetch(endpoint, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Events-Key': publishableKey },
        body: JSON.stringify({ consent: true, url, referrer }),
      });
      if (!response.ok) throw new Error(`attribution_capture_refused: HTTP ${response.status}`);
      const data = await response.json();
      if (!data?.visitor_id || !data?.first_touch || !data?.last_touch) {
        throw new Error('attribution_response_invalid');
      }
      if (consent && revision === generation) { stored = data; return stored; }
    } catch (error) {
      console.warn('[events] attribution_capture_failed: check collector configuration and retry consent capture', error);
    }
    return null;
  });
  pending = run;
  return run;
}

/** Wire to the consuming project's CMP; default is denied. */
export async function setConsent(allowed         )                {
  if (allowed && consent) { await captureAttribution(); return; }
  consent = allowed;
  generation++;
  stored = null;
  if (allowed) {
    const revision = generation;
    await captureAttribution();
    if (consent && revision === generation) listeners.forEach(listener => listener());
  } else {
    listeners.forEach(listener => listener());
    // Wait for any already-sent capture, then clear its server-set cookie.
    pending = pending.then(async () => {
      try {
        const response = await fetch(endpoint, {
          method: 'DELETE', credentials: 'same-origin',
          headers: { 'X-Events-Key': publishableKey },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch (error) {
        console.warn('[events] consent_clear_failed: retry setConsent(false) to delete the server cookie', error);
      }
      return null;
    });
    await pending;
  }
}
