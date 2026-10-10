# JS/TS frontend template

Install [Structured Events Pack 4.3.0](../../packs/structured-events/versions/4.3.0/files/events/README.md),
including all sibling modules and attribution_rules.json. The executable Pack
is the template; this standard does not duplicate its code.

```typescript
import { configureEvents, emitEvent } from './events.ts';
import { startPageViews } from './events_navigation.ts';
configureEvents({ publishableKey: 'project-public-key' });
const stop = startPageViews();
emitEvent({ name: 'ButtonClicked', kind: 'analytics', eventType: 'interaction' });
// Wire unmount to stop().
```

Collection starts on first load with no consent state; collect only
non-personal data. The server owns the visitor cookie; session identity stays in
memory. Every frontend event includes visitor_id, first_touch and last_touch
when capture succeeds. The receiver stamps authenticated actor identity.

startPageViews emits the initial view and one view per path change through
pushState/replaceState/popstate, with the prior page as referrer. Query-only,
fragment-only and state-only updates (filters, the app's own ?selection=all
rewrites) emit nothing; URL snapshots keep rapid navigation accurate. One tracker runs per document,
even across separately bundled copies (a host page and an embedded app): a
second start warns page_views_already_started and returns a no-op cleanup. Do
not manually emit a second initial view. [Google's SPA guidance](https://developers.google.com/analytics/devguides/collection/ga4/single-page-applications)
also describes tracking history changes.

One fetch per batch; only network failures, 429 and 5xx requeue stable event ids.
429 honors Retry-After; other HTTP refusals discard the batch and report the
collector error and recovery. Queues hold at most 500 pending events, dropping
the oldest on append and the newest pending events when preserving retry ids,
and overlapping flushes share an in-flight promise. Visibility hidden flushes
through the same path. The receiver deduplicates event_id. Memory queues are
disposable and product work never depends on delivery. URLs strip sensitive query
keys (including the device-login user_code), credentials and fragments, and
page_url, page_path and referrer mask /machine-approval/<code> as
/machine-approval/redacted; bot user agents are flagged. The browser sends no
device classification: the collector sets browser, browser_version, os and
device_type from the request User-Agent (Bowser) and the Sec-CH-UA-Platform and
Sec-CH-UA-Mobile Client Hints.

api-route.ts supplies anonymous collector and attribution factories. The project
wires a public key, exact Origin checks, shared limiter, deduplicating sink, HTTPS
and private signing secret. Anonymous frontend events require no bearer token.
See [attribution](marketing-attribution.md), [property groups](property-groups.md)
and the Pack guide for server persistence, refusals and recovery.
