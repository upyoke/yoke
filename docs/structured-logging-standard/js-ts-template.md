# JS/TS frontend template

Install [Structured Events Pack 2.0.0](../../packs/structured-events/versions/2.0.0/files/events/README.md),
including all sibling modules and attribution_rules.json. The executable Pack
is the template; this standard does not duplicate its code.

```typescript
import { configureEvents, setConsent, emitEvent } from './events.ts';
import { startPageViews } from './events_navigation.ts';
configureEvents({ publishableKey: 'project-public-key' });
const stop = startPageViews();
await setConsent(consentManager.analyticsAllowed());
emitEvent({ name: 'ButtonClicked', kind: 'analytics', eventType: 'interaction' });
// Wire revocation to await setConsent(false), and unmount to stop().
```

Before consent there is no attribution request/storage or persistent visitor id.
The server owns the visitor cookie; session identity stays in memory. Every
consented frontend event includes visitor_id, first_touch and last_touch when
capture succeeds. The receiver stamps authenticated actor identity.

startPageViews emits the initial view and URL-changing pushState/replaceState/
popstate views with the prior page as referrer. State-only updates are deduped;
URL snapshots keep rapid navigation accurate. Install once; do not manually
emit a second initial view. [Google's SPA guidance](https://developers.google.com/analytics/devguides/collection/ga4/single-page-applications)
also describes tracking history changes.

One fetch per batch; failed sends requeue stable event ids, 429 honors Retry-After,
and overlapping flushes share an in-flight promise. Visibility hidden flushes
through the same path. The receiver deduplicates event_id. Memory queues are
disposable and product work never depends on delivery. URLs strip sensitive query
keys, credentials and fragments; bot user agents are flagged.

api-route.ts supplies anonymous collector and attribution factories. The project
wires a public key, exact Origin checks, shared limiter, deduplicating sink, HTTPS
and private signing secret. Anonymous frontend events require no bearer token.
See [attribution](marketing-attribution.md), [property groups](property-groups.md)
and the Pack guide for consent, server persistence, refusals and recovery.
